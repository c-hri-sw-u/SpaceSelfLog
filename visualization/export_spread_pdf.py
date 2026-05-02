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

        print("Polling iframes for readiness (excluding photowall)...")
        await page.wait_for_function("""
            () => {
                const iframes = document.querySelectorAll('.spread-page iframe');
                if (iframes.length === 0) return true;
                return Array.from(iframes).every(f => {
                    // photowall will be polled separately after switching to fast=0
                    if (f.src && f.src.includes('photowall')) return true;
                    try {
                        const w = f.contentWindow;
                        return typeof w._slideReady === 'undefined' || w._slideReady === true;
                    } catch(e) { return false; }
                });
            }
        """, timeout=60000)

        # ── 1.5 切换 photowall 为真实图片模式 ──
        pw_count = await page.evaluate("""
            let count = 0;
            document.querySelectorAll('.spread-page iframe').forEach(f => {
                if (f.src && f.src.includes('photowall')) {
                    f.src = f.src.replace(/fast=[^&]*/, 'fast=0')
                              + (f.src.includes('fast=') ? '' : '&fast=0');
                    count++;
                }
            });
            count;
        """)
        if pw_count > 0:
            print(f"Switching {pw_count} photowall iframes to real-image mode...")
            # 等 iframe 重新加载
            await page.wait_for_timeout(5000)

            # 用 Playwright frames API 轮询（绕过 contentDocument 跨域问题）
            pw_timeout = 600  # 最多等 10 分钟
            pw_elapsed = 0
            pw_ready = False
            while pw_elapsed < pw_timeout:
                await page.wait_for_timeout(5000)
                pw_elapsed += 5
                try:
                    pw_frames = [f for f in page.frames
                                 if "photowall" in f.url and "fast=0" in f.url]
                    done = 0
                    total_loaded = 0
                    total_images = 0
                    for fr in pw_frames:
                        try:
                            r = await fr.evaluate("""() => {
                                const loaded = parseInt(document.getElementById('progress-count')?.innerText) || 0;
                                const total  = parseInt(document.getElementById('total-count')?.innerText) || 0;
                                const overlay = document.getElementById('loading-overlay');
                                const ready = overlay
                                    ? (overlay.style.display === 'none' || overlay.style.opacity === '0')
                                    : false;
                                return { ready, loaded, total };
                            }""")
                            if r['ready']:
                                done += 1
                            total_loaded += r['loaded']
                            total_images += r['total']
                        except Exception:
                            pass
                    pct = f" ({total_loaded}/{total_images})" if total_images > 0 else ""
                    print(f"  Photowall: {done}/{len(pw_frames)} pages done{pct} ({pw_elapsed}s)")
                    if done >= len(pw_frames) and len(pw_frames) > 0:
                        pw_ready = True
                        break
                except Exception as e:
                    print(f"  Photowall: polling error ({pw_elapsed}s) {e}")

            if not pw_ready:
                print(f"WARNING: Photowall not ready after {pw_timeout}s, proceeding...")

            # 重新轮询 photowall _slideReady（通过 Playwright frames）
            print("Re-polling photowall iframes for _slideReady...")
            pw_elapsed2 = 0
            while pw_elapsed2 < 120:
                await page.wait_for_timeout(5000)
                pw_elapsed2 += 5
                pw_frames = [f for f in page.frames
                             if "photowall" in f.url and "fast=0" in f.url]
                all_ready = True
                for fr in pw_frames:
                    try:
                        r = await fr.evaluate("() => typeof window._slideReady === 'undefined' || window._slideReady === true")
                        if not r:
                            all_ready = False
                    except Exception:
                        all_ready = False
                if all_ready:
                    print(f"  All photowall iframes ready ({pw_elapsed2}s)")
                    break
                print(f"  ... waiting for _slideReady ({pw_elapsed2}s)")
            else:
                print("WARNING: photowall _slideReady not all true, proceeding...")

            # 等待 dots 放置 + 手动触发 overlay 渲染
            print("Waiting for dots to be placed and hi-res overlays to render...")
            await page.wait_for_timeout(5000)  # 等待 setInterval 放置 dots
            pw_frames = [f for f in page.frames
                         if "photowall" in f.url and "fast=0" in f.url]
            for fr in pw_frames:
                try:
                    state = await fr.evaluate("""() => {
                        return {
                            isCanvasReady: typeof isCanvasReady !== 'undefined' ? isCanvasReady : 'undef',
                            hoverIndices: typeof hoverIndices !== 'undefined' ? JSON.stringify(hoverIndices) : 'undef',
                            hiResImages: typeof hiResImages !== 'undefined' ? hiResImages.map(x => x !== null) : 'undef',
                            layoutPoses: typeof cachedLayoutPoses !== 'undefined' ? cachedLayoutPoses.length : 'undef',
                            loadedBitmaps: typeof loadedBitmaps !== 'undefined' ? loadedBitmaps.size : 'undef',
                            filteredImages: typeof FILTERED_IMAGES !== 'undefined' ? FILTERED_IMAGES.length : 'undef',
                            pageCount: typeof PAGE_COUNT !== 'undefined' ? PAGE_COUNT : 'undef',
                        };
                    }""")
                    print(f"  Frame state: {state}")

                    # 手动加载 hi-res 并渲染 overlay
                    await fr.evaluate("""async () => {
                        if (!isCanvasReady || cachedLayoutPoses.length === 0) return;
                        while (hiResImages.length < 2) { hiResImages.push(null); hoverIndices.push(-1); }

                        // 确认 hoverIndices 指向有效图片
                        for (let di = 0; di < 2; di++) {
                            const idx = hoverIndices[di];
                            if (idx === -1 || idx >= FILTERED_IMAGES.length) continue;
                            const url = FILTERED_IMAGES[idx].url;
                            // 检查 loadedBitmaps 是否有这张图
                            if (!loadedBitmaps.has(url)) {
                                console.warn('Missing bitmap for index', idx, url);
                            }
                        }

                        // 手动加载 hi-res 图片（中心放大图）
                        const loadPromises = [];
                        for (let di = 0; di < 2; di++) {
                            const idx = hoverIndices[di];
                            if (idx === -1 || hiResImages[di]) continue;
                            const img = new Image();
                            const p = new Promise((resolve) => {
                                img.onload = () => {
                                    if (hoverIndices[di] === idx) {
                                        hiResImages[di] = img;
                                    }
                                    resolve();
                                };
                                img.onerror = () => {
                                    console.warn('hi-res load failed for index', idx);
                                    resolve();
                                };
                            });
                            img.src = FILTERED_IMAGES[idx].url.replace('thumbnails-data','frames-data');
                            loadPromises.push(p);
                        }
                        await Promise.all(loadPromises);
                        renderAllOverlays();
                    }""")
                    # 检查 overlay 是否有内容
                    check = await fr.evaluate("""() => {
                        const oc = document.getElementById('overlay');
                        if (!oc) return 'no overlay canvas';
                        const ctx = oc.getContext('2d');
                        const data = ctx.getImageData(0, 0, oc.width, oc.height).data;
                        let nonZero = 0;
                        for (let i = 3; i < data.length; i += 4) {
                            if (data[i] > 0) nonZero++;
                        }
                        return {canvasW: oc.width, canvasH: oc.height, nonZeroPixels: nonZero, hiResLoaded: hiResImages.map(x => x !== null)};
                    }""")
                    print(f"  Overlay check: {check}")
                except Exception as e:
                    print(f"  WARNING: hi-res overlay failed: {e}")
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
