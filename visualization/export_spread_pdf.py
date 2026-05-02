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

        # ── 1.5 Blank out photowall iframes to prevent concurrent loading ──
        print("Blanking photowall iframes for sequential loading...")
        pw_iframe_srcs = await page.evaluate("""() => {
            const srcs = [];
            document.querySelectorAll('.spread-page:not(.empty) iframe').forEach(iframe => {
                if (iframe.src && iframe.src.includes('photowall')) {
                    srcs.push({ src: iframe.src, selector: null });
                }
            });
            // Blank them out
            document.querySelectorAll('.spread-page:not(.empty) iframe').forEach(iframe => {
                if (iframe.src && iframe.src.includes('photowall')) {
                    iframe.dataset.originalSrc = iframe.src;
                    iframe.src = 'about:blank';
                }
            });
            return srcs;
        }""")
        print(f"  Found {len(pw_iframe_srcs)} photowall iframes (blanked out)")

        # 1.6 Poll NON-photowall iframes for readiness
        print("Polling non-photowall iframes for readiness...")
        poll_elapsed = 0
        while poll_elapsed < 120:
            await page.wait_for_timeout(5000)
            poll_elapsed += 5
            frames = [f for f in page.frames if f != page.main_frame]
            non_pw_frames = [f for f in frames if "photowall" not in f.url]
            if not non_pw_frames:
                break
            done = 0
            for fr in non_pw_frames:
                try:
                    r = await fr.evaluate("() => typeof window._slideReady === 'undefined' || window._slideReady === true")
                    if r: done += 1
                except Exception:
                    pass
            print(f"  ... {done}/{len(non_pw_frames)} ready ({poll_elapsed}s)")
            if done >= len(non_pw_frames):
                break

        # ── 1.7 Sequentially load photowall iframes one at a time ──
        print("Loading photowall iframes sequentially...")
        # Get all photowall iframe elements with their original srcs
        pw_elements = await page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('.spread-page:not(.empty) iframe').forEach((iframe, i) => {
                if (iframe.dataset.originalSrc) {
                    result.push({ index: i, originalSrc: iframe.dataset.originalSrc });
                }
            });
            return result;
        }""")

        for pi, pw_info in enumerate(pw_elements):
            src = pw_info['originalSrc']
            short = src.split('?')[0].split('/')[-1][:30]
            print(f"  [{pi+1}/{len(pw_elements)}] Loading {short}...")

            # Restore src to trigger load
            await page.evaluate("""(info) => {
                const iframes = document.querySelectorAll('.spread-page:not(.empty) iframe');
                iframes[info.index].src = info.originalSrc;
            }""", pw_info)

            # Poll this specific iframe for readiness
            pw_load_elapsed = 0
            pw_ready = False
            while pw_load_elapsed < 600:  # max 10 min per page
                await page.wait_for_timeout(5000)
                pw_load_elapsed += 5

                # Find the frame that matches this src
                frame = None
                for f in page.frames:
                    if f != page.main_frame and pw_info['originalSrc'] in f.url:
                        frame = f
                        break

                if frame is None:
                    # Frame might not be registered yet
                    print(f"    ... waiting for frame ({pw_load_elapsed}s)")
                    continue

                try:
                    r = await frame.evaluate("""() => {
                        const ready = typeof window._slideReady === 'undefined' || window._slideReady === true;
                        const loaded = parseInt(document.getElementById('progress-count')?.innerText) || 0;
                        const total  = parseInt(document.getElementById('total-count')?.innerText) || 0;
                        const overlay = document.getElementById('loading-overlay');
                        const overlayHidden = overlay ? (overlay.style.display === 'none' || overlay.style.opacity === '0') : true;
                        return { ready, loaded, total, overlayHidden };
                    }""")
                    if r['ready'] and r['overlayHidden']:
                        print(f"    READY ({pw_load_elapsed}s) — {r['loaded']}/{r['total']} images")
                        pw_ready = True
                        break
                    else:
                        pct = f" ({r['loaded']}/{r['total']})" if r['total'] > 0 else ""
                        print(f"    ... loading{pct} ({pw_load_elapsed}s)")
                except Exception as e:
                    print(f"    ... polling error: {e} ({pw_load_elapsed}s)")

            if not pw_ready:
                print(f"    WARNING: {short} not ready after 600s, proceeding...")

            # Small delay between pages to let browser settle
            await page.wait_for_timeout(2000)

        # ── 1.8 Place hi-res overlay dots on all photowall pages ──
        print("Placing hi-res zoom dots on photowall pages...")
        pw_frames = [f for f in page.frames if "photowall" in f.url]
        for fi, fr in enumerate(pw_frames):
            try:
                await fr.evaluate("""async () => {
                    if (typeof cachedLayoutPoses === 'undefined' || cachedLayoutPoses.length === 0) return;
                    const N = cachedLayoutPoses.length;
                    // Place 2 dots per page at different positions
                    while (hiResImages.length < 2) { hiResImages.push(null); hoverIndices.push(-1); }
                    const i1 = Math.floor(N * 0.2 + Math.random() * N * 0.1);
                    const i2 = Math.floor(N * 0.6 + Math.random() * N * 0.15);
                    for (let di = 0; di < 2; di++) {
                        const idx = di === 0 ? i1 : i2;
                        const pos = cachedLayoutPoses[Math.min(idx, N-1)];
                        const px = pos.x + cachedW / 2;
                        const py = pos.y + cachedOffsetY + cachedH / 2;
                        applyHoverAt(px, py, di);
                    }
                    // Load hi-res images
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
                print(f"  [{fi+1}/{len(pw_frames)}] dots placed + hi-res loaded")
            except Exception as e:
                print(f"  WARNING: overlay failed for frame {fi}: {e}")

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
