import asyncio
import io
import sys
from playwright.async_api import async_playwright
from PIL import Image

URL = "http://localhost:8000/slides/"
DPI = 300
FIXED_PX_SCALE = 0.65  # 粒子/描边/字号缩放因子

# Usage: uv run export_spread_pdf.py [--photowall]
PHOTOWALL_ONLY = "--photowall" in sys.argv

async def main():
    output_path = "photowall_export.pdf" if PHOTOWALL_ONLY else "spreads_export.pdf"

    print("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            device_scale_factor=3,
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

        # 1.5 轮询所有 iframe（含 photowall）的 _slideReady
        print("Polling iframes for readiness...")
        if PHOTOWALL_ONLY:
            print("  (photowall-only mode: skipping non-photowall iframes)")
        pw_elapsed = 0
        while pw_elapsed < 600:  # 最多等 10 分钟
            await page.wait_for_timeout(5000)
            pw_elapsed += 5
            pw_frames = [f for f in page.frames if f != page.mainFrame]
            if PHOTOWALL_ONLY:
                pw_frames = [f for f in pw_frames if "photowall" in f.url]
            all_ready = True
            for fr in pw_frames:
                try:
                    r = await fr.evaluate(
                        "() => typeof window._slideReady === 'undefined' || window._slideReady === true",
                        timeout=5000
                    )
                    if not r:
                        all_ready = False
                        break
                except Exception:
                    all_ready = False
                    break
            if all_ready:
                print(f"  All iframes ready ({pw_elapsed}s)")
                break
            # 打印进度
            pw_done = 0
            for fr in pw_frames:
                try:
                    r = await fr.evaluate(
                        "() => typeof window._slideReady === 'undefined' || window._slideReady === true"
                    )
                    if r: pw_done += 1
                except Exception:
                    pass
            print(f"  ... {pw_done}/{len(pw_frames)} ready ({pw_elapsed}s)")
        else:
            print("WARNING: Not all iframes ready after 600s, proceeding...")

        # 1.6 等 photowall overlay dots + hi-res 放大图
        print("Waiting for photowall overlays to render...")
        await page.wait_for_timeout(5000)
        pw_frames = [f for f in page.frames if "photowall" in f.url]
        for fr in pw_frames:
            try:
                await fr.evaluate("""async () => {
                    if (!isCanvasReady || cachedLayoutPoses.length === 0) return;
                    while (hiResImages.length < 2) { hiResImages.push(null); hoverIndices.push(-1); }
                    // 手动加载 hi-res 图片
                    const loadPromises = [];
                    for (let di = 0; di < 2; di++) {
                        const idx = hoverIndices[di];
                        if (idx === -1 || hiResImages[di]) continue;
                        const img = new Image();
                        const p = new Promise((resolve) => {
                            img.onload = () => { if (hoverIndices[di] === idx) hiResImages[di] = img; resolve(); };
                            img.onerror = () => resolve();
                        });
                        img.src = FILTERED_IMAGES[idx].url.replace('thumbnails-data','frames-data');
                        loadPromises.push(p);
                    }
                    await Promise.all(loadPromises);
                    renderAllOverlays();
                }""")
            except Exception as e:
                print(f"  WARNING: overlay render failed: {e}")
        await page.wait_for_timeout(3000)

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
        if PHOTOWALL_ONLY:
            # 只保留 photowall 页面
            filtered = []
            for sp in spread_pages:
                iframe = await sp.query_selector('iframe')
                if iframe:
                    src = await iframe.evaluate("el => el.src")
                    if "photowall" in src:
                        filtered.append(sp)
            print(f"  Filtered to {len(filtered)} photowall pages (from {len(spread_pages)} total)")
            spread_pages = filtered
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
