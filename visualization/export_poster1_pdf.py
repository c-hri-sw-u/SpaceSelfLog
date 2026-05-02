import asyncio
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright

URL = "http://localhost:8000/poster/1"

# CSS 固定 1in=96px，poster 36×78in = 3456×7488 CSS px
# viewport 与 CSS px 1:1，SCALE=1 → headless 稳定渲染所有 iframe
# 96 DPI 对大幅面海报（观看距离 >1m）完全足够
VIEWPORT_W = 3456   # 36 * 96
VIEWPORT_H = 7488   # 78 * 96
SCALE      = 2    # 2x 渲染，输出 6912×14976px (= 192 DPI at 36×78in)

async def main():
    print("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        
        # 精确设置视口大小和缩放比例
        # screenshot 使用的是 viewport 渲染路径，完全不受 PDF reflow 影响
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

        # 等待所有 D3 / iframe 完整渲染
        print("Waiting 15 seconds for D3 to finish rendering...")
        await page.wait_for_timeout(15000)

        print("Cleaning up for export...")
        await page.evaluate("""
            // 去掉 fitToScreen 的缩放 transform，恢复原始尺寸
            const wrapper = document.getElementById('poster-wrapper');
            if (wrapper) { wrapper.style.transform = 'none'; wrapper.style.gap = '0'; }

            // 隐藏参照物
            const refGroup = document.querySelector('.reference-group');
            if (refGroup) refGroup.style.display = 'none';

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

        # 等 transform 移除后布局稳定
        await page.wait_for_timeout(2000)

        # 用 getBoundingClientRect 精确获取 poster-container 的实际位置和尺寸
        rect = await page.eval_on_selector(
            '.poster-container',
            'el => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; }'
        )
        print(f"poster-container rect: {rect}")

        DPI = 192
        output_path = "poster1_export.png"
        print(f"Taking {rect['width']:.0f}x{rect['height']:.0f}px screenshot (2x scale) → {output_path}")
        print(f"(= {DPI} DPI at 36×78in)")

        await page.screenshot(
            path=output_path,
            type="png",
            clip=rect
        )

        # 将 PNG 包装成单页 PDF，告知 Pillow 正确的 DPI
        pdf_path = Path(output_path).with_suffix(".pdf")
        print(f"Converting to PDF → {pdf_path} ...")
        Image.MAX_IMAGE_PIXELS = None
        img = Image.open(output_path).convert('RGB')
        img.save(str(pdf_path), resolution=DPI)

        print("Export successful!")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
