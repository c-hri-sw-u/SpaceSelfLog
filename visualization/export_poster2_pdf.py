import asyncio
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright

URL = "http://localhost:8000/poster/2"

VIEWPORT_W = 3456   # 36 * 96
VIEWPORT_H = 7488   # 78 * 96
SCALE      = 1

async def main():
    print("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch()

        page = await browser.new_page(
            viewport={'width': VIEWPORT_W, 'height': VIEWPORT_H},
            device_scale_factor=SCALE
        )

        print(f"Navigating to {URL} ...")
        try:
            await page.goto(URL, wait_until="networkidle", timeout=120000)
            print("Network idle reached.")
        except Exception:
            print("Network idle timeout, continuing anyway...")

        # 将 iframe 的 fast=1 改为 fast=0，启用真实图片加载
        print("Switching iframe to real image mode (fast=0)...")
        await page.evaluate("""
            const iframe = document.querySelector('iframe');
            if (iframe) {
                iframe.src = iframe.src.replace('fast=1', 'fast=0');
            }
        """)

        # 轮询 iframe 内的 isCanvasReady 变量，自动等待渲染完成
        print("Polling iframe for render completion (isCanvasReady)...")
        timeout_ms = 3_600_000  # 最多等 60 分钟
        poll_interval_ms = 5_000
        elapsed = 0
        ready = False
        while elapsed < timeout_ms:
            await page.wait_for_timeout(poll_interval_ms)
            elapsed += poll_interval_ms
            try:
                ready = await page.evaluate("""
                    const iframe = document.querySelector('iframe');
                    if (!iframe || !iframe.contentWindow) return false;
                    return iframe.contentWindow.isCanvasReady === true;
                """)
            except Exception:
                ready = False
            if ready:
                print(f"Canvas ready after ~{elapsed/1000:.0f}s!")
                break
            print(f"  ... still loading ({elapsed/1000:.0f}s)")

        if not ready:
            print(f"WARNING: Canvas not ready after {timeout_ms/1000:.0f}s, proceeding anyway...")

        print("Cleaning up for export...")
        await page.evaluate("""
            // 去掉 fitToScreen 的缩放 transform
            const wrapper = document.getElementById('poster-wrapper');
            if (wrapper) { wrapper.style.transform = 'none'; wrapper.style.gap = '0'; }

            // 去掉 poster-container 装饰
            const container = document.querySelector('.poster-container');
            if (container) { container.style.boxShadow = 'none'; container.style.border = 'none'; }

            // body 只改背景色，不改 display（保留 flex 以保证 flex-grow 正常计算）
            document.body.style.background = 'white';
            document.body.style.overflow = 'visible';

            // 去阴影
            const s = document.createElement('style');
            s.innerHTML = '* { box-shadow: none !important; text-shadow: none !important; }';
            document.head.appendChild(s);
        """)

        await page.wait_for_timeout(2000)

        rect = await page.eval_on_selector(
            '.poster-container',
            'el => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; }'
        )
        print(f"poster-container rect: {rect}")

        DPI = 96
        output_path = "poster2_export.jpg"
        print(f"Taking {rect['width']:.0f}x{rect['height']:.0f}px screenshot → {output_path}")
        print(f"(= {DPI} DPI at 36×78in)")

        await page.screenshot(
            path=output_path,
            type="jpeg",
            quality=95,
            clip=rect
        )

        pdf_path = Path(output_path).with_suffix(".pdf")
        print(f"Converting to PDF → {pdf_path} ...")
        Image.MAX_IMAGE_PIXELS = None
        img = Image.open(output_path)
        img.save(str(pdf_path), resolution=DPI)

        print("Export successful!")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
