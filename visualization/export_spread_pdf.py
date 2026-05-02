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

        # 将页面结构修改为单页垂直排列，去除红色的中间参考线
        await page.evaluate("""
            // 隐藏工具栏和侧边栏
            document.querySelectorAll('#toolbar, #meta-bar, #sidebar, #script-sidebar, .nav-arrow, #slide').forEach(el => {
                if (el) el.style.display = 'none';
            });

            // 1. 去掉中间的半透明红色矩形 (通过注入 CSS 强制隐藏伪元素)
            const style = document.createElement('style');
            style.innerHTML = `
                .spread-page::after { display: none !important; }
            `;
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

            // 3. 移除在 Spread 模式中为了对齐左右页而自动生成的“空白占位页”（导致了开头的黑页）
            document.querySelectorAll('.spread-page.empty').forEach(el => el.remove());

            // 4. 将原先并排的 spread-row 改为垂直堆叠，打破左右排版
            const rows = document.querySelectorAll('.spread-row');
            rows.forEach(r => {
                r.style.display = 'block';
                r.style.marginBottom = '0px';
                r.style.maxWidth = '100%';
            });
            
            // 5. 对每一个子页面(单页)设置独立的硬分页
            const pages = document.querySelectorAll('.spread-page');
            pages.forEach(p => {
                p.style.boxShadow = 'none';
                p.style.border = 'none';
                p.style.width = '100%';  // 强制撑满纸张宽度
                p.style.pageBreakInside = 'avoid';
                p.style.breakInside = 'avoid';
                p.style.pageBreakAfter = 'always';
            });

            // 6. 遍历所有 iframe 内部，强行去掉所有的阴影（打印 PDF 时阴影常会因缩放 bug 变得巨大）
            const removeShadows = (doc) => {
                if (!doc) return;
                const style = doc.createElement('style');
                style.innerHTML = `
                    * {
                        box-shadow: none !important;
                        text-shadow: none !important;
                    }
                `;
                doc.head.appendChild(style);
            };

            removeShadows(document);
            document.querySelectorAll('iframe').forEach(iframe => {
                try {
                    removeShadows(iframe.contentDocument);
                } catch(e) {}
            });
        """)
        
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
