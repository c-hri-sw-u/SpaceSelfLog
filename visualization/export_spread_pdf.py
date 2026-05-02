import asyncio
import io
from playwright.async_api import async_playwright
from PIL import Image

URL = "http://localhost:8000/slides/"
DPI = 300
FIXED_PX_SCALE = 0.65  # 粒子/描边/字号缩放因子

async def main():
    output_path = "spreads_export.pdf"

    print("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            device_scale_factor=3,
            viewport={"width": 1600, "height": 900}
        )
        page = await context.new_page()

        # ── 在所有 iframe 加载之前注入 Canvas 缩放覆盖 ──
        # add_init_script 会在每个 frame（含 iframe）的 JS 执行之前运行
        print(f"Injecting canvas scale ({FIXED_PX_SCALE}) via init script...")
        await page.add_init_script("""
            const S = %s;

            // 粒子 / 点的半径
            const origArc = CanvasRenderingContext2D.prototype.arc;
            CanvasRenderingContext2D.prototype.arc = function(x, y, r, s, e, ccw) {
                origArc.call(this, x, y, r * S, s, e, ccw);
            };

            // 描边宽度
            const lwDesc = Object.getOwnPropertyDescriptor(
                CanvasRenderingContext2D.prototype, 'lineWidth');
            Object.defineProperty(CanvasRenderingContext2D.prototype, 'lineWidth', {
                set(v) { lwDesc.set.call(this, v * S); },
                get() { return lwDesc.get.call(this); }
            });

            // Canvas 字号（房间标签等）
            const fontDesc = Object.getOwnPropertyDescriptor(
                CanvasRenderingContext2D.prototype, 'font');
            Object.defineProperty(CanvasRenderingContext2D.prototype, 'font', {
                set(v) {
                    const scaled = v.replace(
                        /(%s)d+(?:\\.%sd+)?px/g,
                        function(_, n) { return (parseFloat(n) * S) + 'px'; }
                    );
                    fontDesc.set.call(this, scaled);
                },
                get() { return fontDesc.get.call(this); }
            });
        """ % (FIXED_PX_SCALE, '\\', '\\'))

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

            // SVG 装饰性描边缩放
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

        # 3. 逐页截图
        print("Capturing pages...")
        spread_pages = await page.query_selector_all('.spread-page:not(.empty)')
        screenshots = []

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
