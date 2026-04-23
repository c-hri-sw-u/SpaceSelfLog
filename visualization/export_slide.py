import asyncio
from playwright.async_api import async_playwright

# 3.25 inches * 300 DPI = 975 px
# 2.75 inches * 300 DPI = 825 px
WIDTH = 975
HEIGHT = 825

# 你的本地开发服务器地址
# 这里的端口请替换为你实际跑 slides_routes.py 所在的端口（比如 5001 或 8000）
# 可以直接渲染这一个页面，或者渲染 slides.html?slide=0
URL = "http://localhost:8000/slides/slide-files/00_research_image.html"

async def main():
    print("Launching browser...")
    async with async_playwright() as p:
        # 使用 chromium
        browser = await p.chromium.launch()
        
        # 设置精确的视口大小，device_scale_factor=1 保证 1:1 像素映射
        page = await browser.new_page(
            viewport={'width': WIDTH, 'height': HEIGHT},
            device_scale_factor=1
        )
        
        print(f"Navigating to {URL} ...")
        # networkidle 等待所有网络请求（包括 iframe 内的请求）都完成
        await page.goto(URL, wait_until="networkidle")
        
        # 额外等待 3 秒钟。
        # 这是为了确保 iframe 里的图表（d3.js）、流星连线动画等全部渲染完毕
        print("Waiting 3 seconds for iframes and animations to settle...")
        await page.wait_for_timeout(3000)
        
        output_path = "research_image_export.jpg"
        print(f"Taking screenshot: {output_path}")
        
        # 导出 100% 质量的 JPEG，并严格裁剪尺寸
        await page.screenshot(
            path=output_path,
            type="jpeg",
            quality=100,
            clip={'x': 0, 'y': 0, 'width': WIDTH, 'height': HEIGHT}
        )
        
        print("Export successful!")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
