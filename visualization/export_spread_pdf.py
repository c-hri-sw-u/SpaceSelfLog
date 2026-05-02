import asyncio
from playwright.async_api import async_playwright

URL = "http://localhost:8000/slides/"

async def main():
    print("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        print(f"Navigating to {URL} ...")
        # 1. 初始加载 host 页面
        await page.goto(URL, wait_until="networkidle")

        # 2. 点击 Spread 模式按钮，触发所有的 iframe 动态创建
        print("Switching to Spread Mode...")
        await page.click("#btn-mode-toggle")

        # 3. 关键点：如何等到所有 iframe 加载完毕？
        print("Waiting for all spread iframes to load...")
        
        # 方法 A: 等待网络空闲。这会等待所有的 iframe 内部的 HTML, CSS, JS, 图片等网络请求结束
        # 加上 try-except 是因为如果某些幻灯片包含持续的数据轮询 (polling) 或 WebSocket，
        # networkidle 永远不会触发。这里我们最多等 10 秒，如果还未完全空闲则强制继续。
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            print("Network idle timeout reached. Continuing...")

        print("Waiting 5 seconds for charts to settle...")
        await page.wait_for_timeout(5000)

        # 轮询所有 iframe，等待每个内部的 _slideReady === true
        # 动态 slide 会设 window._slideReady = false 再变 true
        # 静态 slide 不设这个变量 (undefined)，视为已就绪
        print("Polling iframes for readiness signals...")
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

        output_path = "spreads_export.pdf"
        print(f"Exporting PDF to {output_path} ...")
        
        # 为了保留深色背景和原本的视觉效果
        await page.emulate_media(media="screen")

        # 暂停所有动画，冻结为静帧
        await page.evaluate("""
            const freezeAnimations = (doc) => {
                if (!doc) return;
                const style = doc.createElement('style');
                style.innerHTML = `
                    *, *::before, *::after {
                        animation-play-state: paused !important;
                        transition: none !important;
                    }
                `;
                doc.head.appendChild(style);
                doc.getAnimations().forEach(a => a.pause());
            };

            freezeAnimations(document);
            document.querySelectorAll('iframe').forEach(iframe => {
                try { freezeAnimations(iframe.contentDocument); } catch(e) {}
            });
        """)

        # ── Step 1: 修改页面结构为单页垂直排列 ──
        await page.evaluate(“””
            // 隐藏工具栏和侧边栏
            document.querySelectorAll('#toolbar, #meta-bar, #sidebar, #script-sidebar, .nav-arrow, #slide').forEach(el => {
                if (el) el.style.display = 'none';
            });

            // 1. 去掉中间的半透明红色矩形
            const style = document.createElement('style');
            style.innerHTML = `.spread-page::after { display: none !important; }`;
            document.head.appendChild(style);

            // 2. 解放页面滚动容器
            document.body.style.height = 'auto';
            document.body.style.overflow = 'visible';
            document.body.style.background = '#1a1a1a';

            const bodyRow = document.getElementById('body-row');
            if (bodyRow) {
                bodyRow.style.height = 'auto';
                bodyRow.style.overflow = 'visible';
                bodyRow.style.display = 'block';
            }

            const mainNode = document.getElementById('main');
            if (mainNode) {
                mainNode.style.height = 'auto';
                mainNode.style.overflow = 'visible';
                mainNode.style.display = 'block';
                mainNode.style.padding = '0';
            }

            const container = document.getElementById('spread-container');
            if (container) {
                container.style.position = 'static';
                container.style.height = 'auto';
                container.style.overflow = 'visible';
                container.style.padding = '0px';
                container.style.display = 'block';
            }

            // 3. 移除空白占位页
            document.querySelectorAll('.spread-page.empty').forEach(el => el.remove());

            // 4. 将 spread-row 改为垂直堆叠
            document.querySelectorAll('.spread-row').forEach(r => {
                r.style.display = 'block';
                r.style.marginBottom = '0px';
                r.style.maxWidth = '100%';
            });

            // 5. 每个子页面撑满宽度 + 硬分页
            document.querySelectorAll('.spread-page').forEach(p => {
                p.style.boxShadow = 'none';
                p.style.border = 'none';
                p.style.width = '100%';
                p.style.pageBreakInside = 'avoid';
                p.style.breakInside = 'avoid';
                p.style.pageBreakAfter = 'always';
            });

            // 6. 去掉所有阴影
            const removeShadows = (doc) => {
                if (!doc) return;
                const s = doc.createElement('style');
                s.innerHTML = `* { box-shadow: none !important; text-shadow: none !important; }`;
                doc.head.appendChild(s);
            };
            removeShadows(document);
            document.querySelectorAll('iframe').forEach(iframe => {
                try { removeShadows(iframe.contentDocument); } catch(e) {}
            });
        “””)

        # ── Step 2: 等浏览器完成 iframe 重新布局 ──
        # 关键：必须让浏览器有机会重新计算 iframe 尺寸，
        # 否则 iframe 内的 window.innerWidth/innerHeight 还是旧的 spread 模式小尺寸
        print(“Waiting for browser to re-layout iframes...”)
        await page.evaluate(“””
            new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
        “””)
        await page.wait_for_timeout(500)

        # ── Step 3: 现在 iframe 尺寸正确了，触发 resize 让 D3/Canvas 重渲染 ──
        print(“Triggering iframe resize events for re-rendering...”)
        await page.evaluate(“””
            document.querySelectorAll('.spread-page iframe').forEach(iframe => {
                try { iframe.contentWindow.dispatchEvent(new Event('resize')); } catch(e) {}
            });
        “””)

        # 等待重渲染完成
        print(“Waiting for charts to re-render at new dimensions...”)
        await page.wait_for_timeout(3000)
        
        # 4. 导出 PDF
        # 指定输出为单页的 Letter 尺寸 (11 x 8.5 横排)
        await page.pdf(
            path=output_path,
            format="Letter",
            landscape=True,
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"}
        )
        
        print("Export successful!")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
