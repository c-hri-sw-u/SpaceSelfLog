import asyncio
import io
import sys
from playwright.async_api import async_playwright
from PIL import Image

DPI = 300

# Usage:
#   uv run export_photowall_pdf.py              # all 6 pages (one at a time)
#   uv run export_photowall_pdf.py --pages 0-2  # only pages 0,1,2
#   uv run export_photowall_pdf.py --pages 0    # only page 0

# Parse --pages arg
PAGES_ARG = None
for arg in sys.argv:
    if arg.startswith('--pages'):
        PAGES_ARG = arg.split('=')[1]

BASE_URL = "http://localhost:8000/slides/36_results_photowall.html"

async def main():
    print("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            device_scale_factor=3,
            viewport={"width": 1600, "height": 900}
        )
        page = await context.new_page()

        # Determine which pages to export
        # Total: 6 pages = 3 chunks × 2 halves (pg=0,1,2 × half=left,right)
        pages = []
        for pg in range(3):
            for half in ['left', 'right']:
                pages.append((pg, half))

        if PAGES_ARG:
            if '-' in PAGES_ARG:
                a, b = PAGES_ARG.split('-')
                pages = pages[int(a):int(b)+1]
            else:
                idx = int(PAGES_ARG)
                pages = [pages[idx]]

        print(f"Exporting {len(pages)} photowall pages...")

        screenshots = []
        for page_i, (pg, half) in enumerate(pages):
            url = f"{BASE_URL}?pg={pg}&pgs=3&half={half}"
            print(f"\n[{page_i+1}/{len(pages)}] Loading pg={pg} half={half}...")

            await page.goto(url, wait_until='networkidle', timeout=120000)

            # Wait for thumbnails to load
            print("  Waiting for thumbnails to load...")
            ready = False
            elapsed = 0
            while elapsed < 600:
                await page.wait_for_timeout(5000)
                elapsed += 5
                try:
                    r = await page.evaluate("""() => {
                        const ready = window._slideReady === true;
                        const overlay = document.getElementById('loading-overlay');
                        const overlayHidden = overlay && (overlay.style.display === 'none' || overlay.style.opacity === '0');
                        const loaded = parseInt(document.getElementById('progress-count')?.innerText) || 0;
                        const total  = parseInt(document.getElementById('total-count')?.innerText) || 0;
                        return { ready, loaded, total, overlayHidden };
                    }""")
                    if r['ready'] and r['overlayHidden']:
                        print(f"  READY ({elapsed}s) — {r['loaded']}/{r['total']} images")
                        ready = True
                        break
                    pct = f" ({r['loaded']}/{r['total']})" if r['total'] > 0 else ""
                    print(f"  ... loading{pct} ({elapsed}s)")
                except Exception as e:
                    print(f"  ... poll error: {e}")

            if not ready:
                print(f"  WARNING: not ready after {elapsed}s")

            # Place 2 zoom dots away from edges and center seam
            print("  Placing zoom dots...")
            await page.evaluate("""() => {
                if (typeof cachedLayoutPoses === 'undefined' || cachedLayoutPoses.length === 0) return;
                const N = cachedLayoutPoses.length;
                const W = innerDiv.getBoundingClientRect().width;
                const H = innerDiv.getBoundingClientRect().height;
                const safeCandidates = [];
                for (let i = 0; i < N; i++) {
                    const pos = cachedLayoutPoses[i];
                    const px = pos.x + cachedW / 2;
                    const py = pos.y + cachedOffsetY + cachedH / 2;
                    const xRatio = px / W;
                    const yRatio = py / H;
                    const xSafe = (xRatio >= 0.15 && xRatio <= 0.42) || (xRatio >= 0.58 && xRatio <= 0.85);
                    const ySafe = yRatio >= 0.2 && yRatio <= 0.8;
                    if (xSafe && ySafe) safeCandidates.push(i);
                }
                let i1, i2;
                if (safeCandidates.length >= 2) {
                    const mid = Math.floor(safeCandidates.length / 2);
                    i1 = safeCandidates[Math.floor(Math.random() * mid)];
                    i2 = safeCandidates[mid + Math.floor(Math.random() * (safeCandidates.length - mid))];
                } else {
                    i1 = Math.floor(N * 0.25);
                    i2 = Math.floor(N * 0.65);
                }
                while (hiResImages.length < 2) { hiResImages.push(null); hoverIndices.push(-1); }
                for (let di = 0; di < 2; di++) {
                    const idx = di === 0 ? i1 : i2;
                    const pos = cachedLayoutPoses[Math.min(idx, N-1)];
                    const px = pos.x + cachedW / 2;
                    const py = pos.y + cachedOffsetY + cachedH / 2;
                    applyHoverAt(px, py, di);
                }
            }""")
            await page.wait_for_timeout(10000)

            # Final overlay render
            try:
                r = await page.evaluate("""() => {
                    renderAllOverlays();
                    const data = document.getElementById('overlay');
                    const ctx2 = data.getContext('2d');
                    const pixels = ctx2.getImageData(0, 0, Math.min(data.width, 100), Math.min(data.height, 100)).data;
                    let nonZero = 0;
                    for (let i = 3; i < pixels.length; i += 4) { if (pixels[i] > 0) nonZero++; }
                    return { hoverIndices: [...hoverIndices], hiResLoaded: hiResImages.map(x => x !== null), overlayPixels: nonZero };
                }""")
                print(f"  Overlay: {r}")
            except Exception as e:
                print(f"  Overlay render error: {e}")

            # Hide yellow dots + page indicator
            await page.evaluate("""() => {
                document.querySelectorAll('.fake-cursor-dot').forEach(d => d.classList.remove('visible'));
            }""")
            await page.wait_for_timeout(500)

            # Freeze animations
            await page.evaluate("""() => {
                const s = document.createElement('style');
                s.innerHTML = `*, *::before, *::after { animation-play-state: paused !important; transition: none !important; }`;
                document.head.appendChild(s);
                document.getAnimations().forEach(a => a.pause());
            }""")

            # Screenshot the container
            # For 'left' half, clip to left half; for 'right', clip to right
            rect = await page.evaluate("""() => {
                const el = document.getElementById('container');
                const r = el.getBoundingClientRect();
                return { x: r.x, y: r.y, width: r.width, height: r.height };
            }""")

            if half == 'left':
                clip = {'x': 0, 'y': 0, 'width': rect['width'] / 2, 'height': rect['height']}
            else:
                clip = {'x': rect['width'] / 2, 'y': 0, 'width': rect['width'] / 2, 'height': rect['height']}

            print(f"  Screenshotting {clip['width']:.0f}x{clip['height']:.0f}...")
            raw = await page.screenshot(type='png', clip=clip)
            screenshots.append(raw)
            print(f"  Done pg={pg} half={half}")

        await browser.close()

    # Build PDF
    output_path = "photowall_export.pdf"
    print(f"\nBuilding PDF ({DPI} DPI) -> {output_path} ...")
    target_w = int(11 * DPI)    # 3300 px
    target_h = int(8.5 * DPI)   # 2550 px

    pdf_pages = []
    for raw in screenshots:
        img = Image.open(io.BytesIO(raw)).convert('RGB')
        pdf_pages.append(img.resize((target_w, target_h), Image.LANCZOS))

    pdf_pages[0].save(
        output_path, "PDF",
        save_all=True, append_images=pdf_pages[1:],
        resolution=DPI
    )
    print(f"Done! {len(pdf_pages)} pages -> {output_path}")

if __name__ == "__main__":
    asyncio.run(main())
