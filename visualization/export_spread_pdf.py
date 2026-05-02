import asyncio
import io
import re
import sys
from playwright.async_api import async_playwright
from PIL import Image

URL = "http://localhost:8000/slides/"
DPI = 300
FIXED_PX_SCALE = 0.65  # 粒子/描边/字号缩放因子

# ── CLI parsing ──
# Usage:
#   uv run export_spread_pdf.py                     # all slides
#   uv run export_spread_pdf.py --photowall         # all 6 photowall pages
#   uv run export_spread_pdf.py --photowall --1/3   # group 1 of 3 (pages 0-1)
#   uv run export_spread_pdf.py --photowall --2/3   # group 2 of 3 (pages 2-3)
#   uv run export_spread_pdf.py --photowall --3/3   # group 3 of 3 (pages 4-5)
PHOTOWALL_ONLY = "--photowall" in sys.argv

_group_match = None
for arg in sys.argv:
    m = re.match(r'^--(\d+)/(\d+)$', arg)
    if m:
        _group_match = (int(m.group(1)), int(m.group(2)))
        break
GROUP_N, GROUP_TOTAL = _group_match if _group_match else (None, None)

async def main():
    if GROUP_N is not None:
        output_path = f"photowall_export_{GROUP_N}of{GROUP_TOTAL}.pdf"
    elif PHOTOWALL_ONLY:
        output_path = "photowall_export.pdf"
    else:
        output_path = "spreads_export.pdf"

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
        total_pw = len(pw_iframe_srcs)
        print(f"  Found {total_pw} photowall iframes (blanked out)")

        # ── Calculate page range for this group ──
        if GROUP_N is not None and GROUP_TOTAL is not None:
            pages_per_group = -(-total_pw // GROUP_TOTAL)  # ceil division
            page_start = (GROUP_N - 1) * pages_per_group
            page_end = min(page_start + pages_per_group, total_pw)
            page_indices = list(range(page_start, page_end))
            print(f"  Group {GROUP_N}/{GROUP_TOTAL}: pages {page_start}-{page_end-1} ({len(page_indices)} pages)")
        else:
            page_indices = list(range(total_pw))

        # 1.6 Poll NON-photowall iframes for readiness
        if not PHOTOWALL_ONLY:
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

        # ── 1.7 Sequentially load ONLY this group's photowall iframes ──
        print(f"Loading photowall iframes sequentially ({len(page_indices)} pages)...")
        pw_elements = await page.evaluate("""() => {
            const result = [];
            document.querySelectorAll('.spread-page:not(.empty) iframe').forEach((iframe, i) => {
                if (iframe.dataset.originalSrc) {
                    result.push({ index: i, originalSrc: iframe.dataset.originalSrc });
                }
            });
            return result;
        }""")

        loaded_pw_srcs = []  # track which srcs we loaded (for filtering screenshots)
        for load_i, pw_global_i in enumerate(page_indices):
            pw_info = pw_elements[pw_global_i]
            src = pw_info['originalSrc']
            short = src.split('?')[0].split('/')[-1][:30]
            print(f"  [{load_i+1}/{len(page_indices)}] Loading {short}...")

            # Restore src to trigger load
            await page.evaluate("""(info) => {
                const iframes = document.querySelectorAll('.spread-page:not(.empty) iframe');
                iframes[info.index].src = info.originalSrc;
            }""", pw_info)

            # Get the iframe element handle, then its content frame
            iframe_handle = await page.evaluate_handle(
                """(idx) => document.querySelectorAll('.spread-page:not(.empty) iframe')[idx]""",
                pw_info['index']
            )
            cf = iframe_handle.content_frame()
            # Some Playwright versions return a coroutine, others return Frame directly
            if asyncio.iscoroutine(cf):
                frame = await cf
            else:
                frame = cf

            if frame is None:
                # Fallback: wait for frame to appear by URL
                print("    content_frame() returned None, waiting for frame...")
                frame = None
                for _ in range(30):
                    await page.wait_for_timeout(1000)
                    for f in page.frames:
                        if f != page.main_frame and "photowall" in f.url and "about:blank" not in f.url:
                            frame = f
                            break
                    if frame:
                        break
                if frame is None:
                    print(f"    WARNING: could not find frame, skipping")
                    continue

            # Wait for frame to navigate away from about:blank
            print("    Waiting for frame navigation...")
            for _ in range(60):
                await page.wait_for_timeout(1000)
                try:
                    url = frame.url
                    if "photowall" in url:
                        print(f"    Frame navigated: {url[:80]}")
                        break
                except Exception:
                    pass
            else:
                print(f"    WARNING: frame did not navigate, skipping")
                continue

            # Wait for DOM to be ready
            try:
                await frame.wait_for_load_state('domcontentloaded', timeout=30000)
            except Exception:
                pass

            # Poll for readiness (strict: _slideReady must be true, overlay must exist AND be hidden)
            pw_load_elapsed = 0
            pw_ready = False
            while pw_load_elapsed < 600:  # max 10 min per page
                await page.wait_for_timeout(5000)
                pw_load_elapsed += 5

                try:
                    r = await frame.evaluate("""() => {
                        const ready = window._slideReady === true;
                        const overlay = document.getElementById('loading-overlay');
                        const overlayExists = overlay !== null;
                        const overlayHidden = overlayExists && (overlay.style.display === 'none' || overlay.style.opacity === '0');
                        const loaded = parseInt(document.getElementById('progress-count')?.innerText) || 0;
                        const total  = parseInt(document.getElementById('total-count')?.innerText) || 0;
                        return { ready, loaded, total, overlayHidden, overlayExists };
                    }""")
                    if r['ready'] and r['overlayExists'] and r['overlayHidden']:
                        print(f"    READY ({pw_load_elapsed}s) — {r['loaded']}/{r['total']} images")
                        pw_ready = True
                        break
                    else:
                        pct = f" ({r['loaded']}/{r['total']})" if r['total'] > 0 else ""
                        state = []
                        if not r['overlayExists']: state.append("no overlay")
                        if not r['overlayHidden']: state.append("overlay visible")
                        if not r['ready']: state.append("not ready")
                        print(f"    ... loading{pct} [{', '.join(state)}] ({pw_load_elapsed}s)")
                except Exception as e:
                    print(f"    ... polling error: {e} ({pw_load_elapsed}s)")

            if not pw_ready:
                print(f"    WARNING: {short} not ready after 600s, proceeding...")

            loaded_pw_srcs.append(pw_info['originalSrc'])
            await page.wait_for_timeout(2000)

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

            const hideGuides = document.createElement('style');
            hideGuides.innerHTML = `.spread-page::after { display: none !important; }`;
            document.head.appendChild(hideGuides);

            document.querySelectorAll('.spread-page').forEach(p => {
                p.style.boxShadow = 'none';
                p.style.border = 'none';
            });

            document.querySelectorAll('iframe').forEach(f => {
                try {
                    const s = f.contentDocument.createElement('style');
                    s.innerHTML = `* { box-shadow: none !important; }`;
                    f.contentDocument.head.appendChild(s);
                } catch(e) {}
            });

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

        # ── 2.5 Place hi-res overlay dots AFTER freeze ──
        # Only on the photowall frames we actually loaded
        print("Disabling resize handlers & placing overlay dots...")
        pw_frames = [f for f in page.frames if "photowall" in f.url
                     and any(s in f.url for s in loaded_pw_srcs)]

        for fi, fr in enumerate(pw_frames):
            try:
                await fr.evaluate("""() => {
                    window.removeEventListener('resize', resizeCanvas);
                }""")
            except Exception:
                pass

        for fi, fr in enumerate(pw_frames):
            try:
                await fr.evaluate("""async () => {
                    if (typeof cachedLayoutPoses === 'undefined' || cachedLayoutPoses.length === 0) return;
                    const N = cachedLayoutPoses.length;
                    const i1 = Math.floor(N * 0.2 + Math.random() * N * 0.1);
                    const i2 = Math.floor(N * 0.6 + Math.random() * N * 0.15);
                    while (hiResImages.length < 2) { hiResImages.push(null); hoverIndices.push(-1); }
                    for (let di = 0; di < 2; di++) {
                        const idx = di === 0 ? i1 : i2;
                        const pos = cachedLayoutPoses[Math.min(idx, N-1)];
                        const px = pos.x + cachedW / 2;
                        const py = pos.y + cachedOffsetY + cachedH / 2;
                        applyHoverAt(px, py, di);
                        await new Promise(r => setTimeout(r, 2000));
                    }
                }""")
                print(f"  [{fi+1}/{len(pw_frames)}] dots placed")
            except Exception as e:
                print(f"  WARNING: dot placement failed for frame {fi}: {e}")

        print("Waiting 15s for hi-res images to load...")
        await page.wait_for_timeout(15_000)

        print("Final overlay render...")
        for fi, fr in enumerate(pw_frames):
            try:
                r = await fr.evaluate("""() => {
                    if (typeof renderAllOverlays !== 'function') return { ok: false, reason: 'no function' };
                    renderAllOverlays();
                    const data = document.getElementById('overlay');
                    const ctx2 = data.getContext('2d');
                    const pixels = ctx2.getImageData(0, 0, Math.min(data.width, 100), Math.min(data.height, 100)).data;
                    let nonZero = 0;
                    for (let i = 3; i < pixels.length; i += 4) { if (pixels[i] > 0) nonZero++; }
                    return { ok: true, hoverIndices: [...hoverIndices], hiResLoaded: hiResImages.map(x => x !== null), overlayPixels: nonZero };
                }""")
                print(f"  [{fi+1}/{len(pw_frames)}] {r}")
            except Exception as e:
                print(f"  WARNING: final render failed for frame {fi}: {e}")

        await page.wait_for_timeout(2000)

        # 3. 逐页截图
        print("Capturing pages...")
        spread_pages = await page.query_selector_all('.spread-page:not(.empty)')

        if PHOTOWALL_ONLY or GROUP_N is not None:
            filtered = []
            for sp in spread_pages:
                iframe = await sp.query_selector('iframe')
                if iframe:
                    src = await iframe.evaluate("el => el.src")
                    if "photowall" in src and any(s in src for s in loaded_pw_srcs):
                        filtered.append(sp)
            print(f"  Filtered to {len(filtered)} photowall pages")
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
