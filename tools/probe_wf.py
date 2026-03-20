"""Probe Wells Fargo login page and dump HTML for selector discovery."""
import asyncio
from playwright.async_api import async_playwright


async def probe():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Loading WF login page...")
        await page.goto(
            "https://connect.secure.wellsfargo.com/auth/login/present",
            timeout=60000,
        )
        html = await page.content()
        with open("/tmp/wf_probe.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved {len(html)} bytes to /tmp/wf_probe.html")
        await browser.close()


asyncio.run(probe())
