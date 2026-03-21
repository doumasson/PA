"""Probe Wells Fargo login page and dump HTML for selector discovery."""
import asyncio
from playwright.async_api import async_playwright


async def probe():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--js-flags=--max-old-space-size=256",
            ],
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        # Block images, fonts, analytics to speed up on Pi
        await ctx.route(
            "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,eot}",
            lambda route: route.abort(),
        )
        await ctx.route(
            "**/{analytics,tracking,ads,beacon,pixel}**",
            lambda route: route.abort(),
        )
        page = await ctx.new_page()
        print("Loading WF login page...")
        await page.goto(
            "https://connect.secure.wellsfargo.com/auth/login/present",
            timeout=120000,
        )
        html = await page.content()
        with open("/tmp/wf_probe.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved {len(html)} bytes to /tmp/wf_probe.html")
        await browser.close()


asyncio.run(probe())
