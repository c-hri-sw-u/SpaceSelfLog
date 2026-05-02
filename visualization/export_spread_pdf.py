import asyncio
import io
import os
import tempfile
import shutil
from playwright.async_api import async_playwright
from PIL import Image

URL = "http://localhost:8000/slides/"
DPI = 300  # 印刷级清晰度

async def main():
    output_path = "spreads_export.pdf"

    print("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            device_scale_factor=2,   # 2× 截图，避免 Canvas/粒子因 DPR 过渲染
            viewport={"width": 1600, "height": 900}
        )
        page = await context.new_page()

        # 1. 加载并渲染 Spread 模式
        print(f"Navigating to {URL} ...")
        await page.goto(URL, wait_until="networkidle")

        print("Switching to Spread Mode...")
        await page.click("#btn-mode-toggle")

        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            print("Network idle timeout. Continuing...")

        print("Waiting for charts to settle...")
        await page.wait_for_timeout(5000)

        print("Polling iframes for readiness...")
        await page.wait_for_function("""
            () => {
                const iframes = document.querySelectorAll('.spread-page iframe');
                if (iframes.length === 0) return true;
                return Array.from(iframes).every(f => {
                    try {
                        const w = f.contentWindow;
                        return typeof w._slideReady === 'undefined' || w._slideReady === true;
                    } catch(e) { return false; }
                });
            }
        """, timeout=30000)

        # 2. 冻结动画 + 清理视觉元素
        print("Freezing animations & cleaning visuals...")
        await page.evaluate("""
            const freeze = (doc) => {
                if (!doc) return;
                const s = doc.createElement('style');
                s.innerHTML = `
                    *, *::before, *::after {
                        animation-play-state: paused !important;
                        transition: none !important;
                    }
                `;
                doc.head.appendChild(s);
                doc.getAnimations().forEach(a => a.pause());
            };
            freeze(document);
            document.querySelectorAll('iframe').forEach(f => {
                try { freeze(f.contentDocument); } catch(e) {}
            });

            // 关闭红色参考线
            const hideGuides = document.createElement('style');
            hideGuides.innerHTML = `.spread-page::after { display: none !important; }`;
            document.head.appendChild(hideGuides);

            // 去掉 spread-page 外框阴影
            document.querySelectorAll('.spread-page').forEach(p => {
                p.style.boxShadow = 'none';
                p.style.border = 'none';
            });

            // 去掉 iframe 内部阴影
            document.querySelectorAll('iframe').forEach(f => {
                try {
                    const s = f.contentDocument.createElement('style');
                    s.innerHTML = `* { box-shadow: none !important; }`;
                    f.contentDocument.head.appendChild(s);
                } catch(e) {}
            });
        """)

        # 3. 按比例缩放 Canvas 中的固定 px 元素（粒子、描边、字号）
        #    spread-page ~800px，但粒子/描边是固定 px 不随 viewport 缩放，
        #    需要乘以 iframeWidth / parentWidth 使之与 vw 元素比例一致
        FIXED_PX_SCALE = 0.65
        print(f"Injecting fixed-px scale ({FIXED_PX_SCALE}) into iframes...")
        await page.evaluate("""
            const S = %s;
            document.querySelectorAll('.spread-page iframe').forEach(iframe => {
                try {
                    const win = iframe.contentWindow;
                    const proto = win.CanvasRenderingContext2D.prototype;

                    // 粒子 / 点的半径
                    const origArc = proto.arc;
                    proto.arc = function(x, y, r, s, e, ccw) {
                        origArc.call(this, x, y, r * S, s, e, ccw);
                    };

                    // 描边宽度
                    const lwDesc = Object.getOwnPropertyDescriptor(proto, 'lineWidth');
                    Object.defineProperty(proto, 'lineWidth', {
                        set(v) { lwDesc.set.call(this, v * S); },
                        get() { return lwDesc.get.call(this); }
                    });

                    // Canvas 字号（房间标签等）
                    const fontDesc = Object.getOwnPropertyDescriptor(proto, 'font');
                    Object.defineProperty(proto, 'font', {
                        set(v) {
                            const scaled = v.replace(
                                /(\\d+(?:\\.\\d+)?)px/g,
                                (_, n) => (parseFloat(n) * S) + 'px'
                            );
                            fontDesc.set.call(this, scaled);
                        },
                        get() { return fontDesc.get.call(this); }
                    });

                    // 清空画布，触发重绘
                    iframe.contentDocument.querySelectorAll('canvas').forEach(c => {
                        c.getContext('2d').clearRect(0, 0, c.width, c.height);
                    });
                    win.dispatchEvent(new Event('resize'));
                } catch(e) { console.error(e); }
            });
        """ % FIXED_PX_SCALE)

        print("Waiting for canvases to re-render...")
        await page.wait_for_timeout(3000)

        # SVG 装饰性描边（donut 间隔线等，不碰 sankey 数据宽度）
        await page.evaluate("""
            const S = %s;
            document.querySelectorAll('.spread-page iframe').forEach(iframe => {
                try {
                    iframe.contentDocument.querySelectorAll('[stroke-width]').forEach(el => {
                        const w = parseFloat(el.getAttribute('stroke-width'));
                        if (w && w < 5)
                            el.setAttribute('stroke-width', (w * S).toFixed(2));
                    });
                } catch(e) {}
            });
        """ % FIXED_PX_SCALE)

        # 4. 逐页截图
        print("Capturing pages...")
        spread_pages = await page.query_selector_all('.spread-page:not(.empty)')
        screenshots = []  # list of (bytes, is_wide)

        for i, sp in enumerate(spread_pages):
            is_wide = await sp.evaluate("el => el.classList.contains('wide-page')")
            tag = "wide" if is_wide else "normal"
            print(f"  {i+1}/{len(spread_pages)} ({tag})")
            await sp.scroll_into_view_if_needed()
            await page.wait_for_timeout(100)
            raw = await sp.screenshot(type='png')
            screenshots.append((raw, is_wide))

        await browser.close()

    # 4. 用 Pillow 拼装 PDF
    print(f"Building PDF ({DPI} DPI) -> {output_path} ...")

    target_w = int(11 * DPI)    # 3300 px
    target_h = int(8.5 * DPI)   # 2550 px

    pdf_pages = []
    for raw, is_wide in screenshots:
        img = Image.open(io.BytesIO(raw)).convert('RGB')

        if is_wide:
            w, h = img.size
            left  = img.crop((0, 0, w // 2, h)).resize((target_w, target_h), Image.LANCZOS)
            right = img.crop((w // 2, 0, w, h)).resize((target_w, target_h), Image.LANCZOS)
            pdf_pages.append(left)
            pdf_pages.append(right)
        else:
            pdf_pages.append(img.resize((target_w, target_h), Image.LANCZOS))

    pdf_pages[0].save(
        output_path,
        "PDF",
        save_all=True,
        append_images=pdf_pages[1:],
        resolution=DPI
    )

    print(f"Done! {len(pdf_pages)} pages -> {output_path}")

if __name__ == "__main__":
    asyncio.run(main())
