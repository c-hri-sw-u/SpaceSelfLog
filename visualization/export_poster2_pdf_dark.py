import asyncio
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright

URL = "http://localhost:8000/poster/2"

VIEWPORT_W = 3456   # 36 * 96
VIEWPORT_H = 7488   # 78 * 96
SCALE      = 2    # 2x 渲染，输出 6912×14976px (= 192 DPI at 36×78in)

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

        # 将 iframe 改为 dark 主题 + 真实图片加载，加 cache-buster 强制重新加载
        print("Switching iframe to dark theme + real image mode...")
        await page.evaluate("""
            const iframe = document.querySelector('iframe');
            if (iframe) {
                iframe.src = iframe.src.replace('fast=1', 'fast=0').replace('theme=light', 'theme=dark') + '&_t=' + Date.now();
            }
        """)

        # Phase 1: 等 iframe 重新加载，确认新页面已初始化（total-count > 0 且 URL 含 fast=0）
        print("Waiting for iframe to reload with fast=0...")
        iframe_reloaded = False
        for _ in range(60):  # 最多等 5 分钟
            await page.wait_for_timeout(5_000)
            try:
                frame = next((f for f in page.frames if "photowall" in f.url), None)
                if frame is None:
                    continue
                if "fast=0" not in frame.url:
                    continue
                total_text = await frame.evaluate("""() => {
                    return document.getElementById('total-count')?.innerText || '';
                }""")
                total = int(total_text) if total_text.isdigit() else 0
                if total > 0:
                    print(f"  iframe reloaded, total images: {total}")
                    iframe_reloaded = True
                    break
            except Exception:
                pass
            print(f"  ... waiting for iframe reload")

        if not iframe_reloaded:
            print("WARNING: iframe did not reload, proceeding anyway...")

        # Phase 2: 轮询 isCanvasReady，显示进度
        print("Polling iframe for render completion (isCanvasReady)...")
        timeout_ms = 3_600_000  # 最多等 60 分钟
        poll_interval_ms = 5_000
        elapsed = 0
        ready = False
        while elapsed < timeout_ms:
            await page.wait_for_timeout(poll_interval_ms)
            elapsed += poll_interval_ms
            try:
                frame = next((f for f in page.frames if "photowall" in f.url), None)
                if frame is None:
                    print(f"  ... iframe not found ({elapsed/1000:.0f}s)")
                    continue
                result = await frame.evaluate("""() => {
                    const loaded = parseInt(document.getElementById('progress-count')?.innerText) || 0;
                    const total  = parseInt(document.getElementById('total-count')?.innerText) || 0;
                    const overlay = document.getElementById('loading-overlay');
                    const overlayHidden = overlay ? (overlay.style.display === 'none' || overlay.style.opacity === '0') : false;
                    return { ready: overlayHidden, loaded, total };
                }""")
                ready = result['ready']
                loaded = result['loaded']
                total = result['total']
            except Exception as e:
                print(f"  [poll error: {e}]")
                ready, loaded, total = False, 0, 0
            if ready:
                print(f"Canvas ready after ~{elapsed/1000:.0f}s!")
                break
            pct = f" ({loaded}/{total})" if total > 0 else ""
            print(f"  ... loading{pct} ({elapsed/1000:.0f}s)")

        if not ready:
            print(f"WARNING: Canvas not ready after {timeout_ms/1000:.0f}s, proceeding anyway...")

        # 在 iframe 内手动放置 12 个 hi-res 放大圆点（绕过 PAGE_COUNT < 2 的限制）
        print("Placing hi-res zoom dots in iframe...")
        try:
            frame = next((f for f in page.frames if "photowall" in f.url), None)
            if frame:
                # 先放 12 个点，扩展 hoverIndices/hiResImages
                await frame.evaluate("""async () => {
                    if (typeof cachedLayoutPoses === 'undefined' || cachedLayoutPoses.length === 0) return;
                    const N = cachedLayoutPoses.length;
                    const bases = [
                        Math.floor(N * 0.05 + Math.random() * N * 0.04),
                        Math.floor(N * 0.16 + Math.random() * N * 0.04),
                        Math.floor(N * 0.27 + Math.random() * N * 0.04),
                        Math.floor(N * 0.38 + Math.random() * N * 0.04),
                        Math.floor(N * 0.49 + Math.random() * N * 0.04),
                        Math.floor(N * 0.60 + Math.random() * N * 0.04),
                        Math.floor(N * 0.73 + Math.random() * N * 0.04),
                        Math.floor(N * 0.88 + Math.random() * N * 0.04),
                    ];
                    const extra = [0,1,2,3,4,5,6,7].sort(() => Math.random() - 0.5).slice(0, 4);
                    const indices = [...bases];
                    for (const row of extra) {
                        const center = bases[row];
                        const lo = Math.max(0, center - 50);
                        const hi = Math.min(N - 1, center + 50);
                        let candidate;
                        do { candidate = lo + Math.floor(Math.random() * (hi - lo + 1)); }
                        while (candidate === center && (hi - lo) > 0);
                        indices.push(candidate);
                    }
                    while (hiResImages.length < indices.length) { hiResImages.push(null); hoverIndices.push(-1); }
                    for (let di = 0; di < indices.length; di++) {
                        const pos = cachedLayoutPoses[indices[di]];
                        const px = pos.x + cachedW / 2;
                        const py = pos.y + cachedOffsetY + cachedH / 2;
                        applyHoverAt(px, py, di);
                        await new Promise(r => setTimeout(r, 2000));
                    }
                }""")
                # 放完点后 patch renderAllOverlays（白色标注文字 + 白色阴影，适配黑背景）
                await frame.evaluate("""() => {
                    const DOCK_COUNT = hoverIndices.length;
                    renderAllOverlays = function() {
                        const rect = innerDiv.getBoundingClientRect();
                        const bs = rect.width / 1600;
                        oCtx.save(); oCtx.setTransform(1,0,0,1,0,0); oCtx.clearRect(0,0,overlayCanvas.width,overlayCanvas.height); oCtx.restore();
                        for (let di = 0; di < DOCK_COUNT; di++) {
                            const imgIdx = hoverIndices[di];
                            if (imgIdx === -1) continue;
                            for (const it of buildDock(imgIdx, rect)) {
                                const imgObj = FILTERED_IMAGES[it.idx];
                                const bmp = (it.k === 0 && hiResImages[di]) ? hiResImages[di] : loadedBitmaps.get(imgObj.url);
                                if (!bmp) continue;
                                oCtx.shadowColor='rgba(255,255,255,0.6)'; oCtx.shadowBlur=10*bs*it.s; oCtx.shadowOffsetX=0; oCtx.shadowOffsetY=5*bs*it.s; oCtx.globalAlpha=1.0;
                                oCtx.drawImage(bmp, it.x, it.y, it.w, it.h);
                                oCtx.shadowColor='transparent'; oCtx.strokeStyle='rgba(255,255,255,0.9)'; oCtx.lineWidth=bs+it.s*0.2;
                                oCtx.strokeRect(it.x, it.y, it.w, it.h);
                                if (it.k === 0) {
                                    const d = new Date(imgObj.ts);
                                    const ts = `${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
                                    oCtx.font=`bold ${bs*13}px 'Courier New',monospace`;
                                    const tW=oCtx.measureText(ts).width, tx=it.x+it.w/2-tW/2, ty=it.y-28*bs;
                                    oCtx.fillStyle = 'rgba(0,0,0,0.85)';
                                    oCtx.fillRect(tx-10*bs,ty,tW+20*bs,22*bs);
                                    oCtx.fillStyle = 'rgba(255,255,255,1)';
                                    oCtx.fillText(ts,tx,ty+15*bs);
                                }
                            }
                        }
                    };
                }""")
                print("Waiting for hi-res images to finish loading...")
                await page.wait_for_timeout(15_000)
                await frame.evaluate("""() => {
                    if (typeof renderAllOverlays === 'function') renderAllOverlays();
                }""")
                await page.wait_for_timeout(2_000)
        except Exception as e:
            print(f"WARNING: could not place zoom dots: {e}")

        print("Cleaning up for export (dark theme)...")
        await page.evaluate("""
            // 去掉 fitToScreen 的缩放 transform
            const wrapper = document.getElementById('poster-wrapper');
            if (wrapper) { wrapper.style.transform = 'none'; wrapper.style.gap = '0'; }

            // 去掉 poster-container 装饰
            const container = document.querySelector('.poster-container');
            if (container) { container.style.boxShadow = 'none'; container.style.border = 'none'; }

            // 黑色背景
            document.body.style.background = 'black';
            document.body.style.overflow = 'visible';

            // poster-container 也改成黑色背景
            if (container) container.style.background = '#000';

            // 照片墙区域背景也改成黑色
            const wall = document.querySelector('.poster-sec-wall');
            if (wall) wall.style.background = '#000';

            // 去阴影
            const s = document.createElement('style');
            s.innerHTML = '* { box-shadow: none !important; text-shadow: none !important; }';
            document.head.appendChild(s);
        """)

        # 漫画区域图片加白色边框
        await page.evaluate("""
            document.querySelectorAll('.poster-sec-manga img').forEach(img => {
                img.style.border = '0.05in solid #fff';
            });
        """)

        await page.wait_for_timeout(2000)

        rect = await page.eval_on_selector(
            '.poster-container',
            'el => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; }'
        )
        print(f"poster-container rect: {rect}")

        DPI = 192
        output_path = "poster2_export_dark.jpg"
        print(f"Taking {rect['width']:.0f}x{rect['height']:.0f}px screenshot (2x scale) → {output_path}")
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
