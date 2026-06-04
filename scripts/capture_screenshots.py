"""Capture polished screenshots of the live (or local) demo for the README.

Usage:
    python scripts/capture_screenshots.py                       # uses live demo URL
    python scripts/capture_screenshots.py http://localhost:3000 # local

Requires:
    pip install playwright && playwright install chromium

Captured (1920x1080):
    docs/screenshots/01-landing.png
    docs/screenshots/02-login.png
    docs/screenshots/03-streaming.png
    docs/screenshots/04-trace.png
    docs/screenshots/05-dashboard.png
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

from playwright.async_api import async_playwright


DEFAULT_URL = "https://career-showcase-511.emergent.host"
EMAIL = "admin@decision-engine.dev"
PASSWORD = "admin123"

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


async def main(base_url: str):
    qid = uuid.uuid4().hex[:8]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        # 1. Landing
        await page.goto(f"{base_url}/", wait_until="networkidle")
        await page.wait_for_timeout(1200)
        await page.screenshot(path=str(OUT / "01-landing.png"))
        print("✓ 01-landing.png")

        # 2. Login screen
        await page.goto(f"{base_url}/login", wait_until="networkidle")
        await page.wait_for_timeout(800)
        await page.screenshot(path=str(OUT / "02-login.png"))
        print("✓ 02-login.png")

        # 3. Sign in & ask
        await page.fill('[data-testid="login-email-input"]', EMAIL)
        await page.fill('[data-testid="login-password-input"]', PASSWORD)
        await page.click('[data-testid="login-submit-btn"]')
        await page.wait_for_url("**/app", timeout=15000)
        await page.wait_for_timeout(800)
        await page.click('[data-testid="new-thread-btn"]')
        await page.wait_for_timeout(400)
        await page.fill(
            '[data-testid="ask-input"]',
            f"Explain knowledge distillation in transformers — variant {qid}.",
        )
        await page.click('[data-testid="ask-submit-btn"]')
        await page.wait_for_selector('[data-testid="live-pipeline"]', timeout=8000)
        await page.wait_for_timeout(2800)
        await page.screenshot(path=str(OUT / "03-streaming.png"))
        print("✓ 03-streaming.png")

        # 4. Final answer + agent trace
        await page.wait_for_selector('[data-testid="message-assistant-1"]', timeout=90000)
        await page.wait_for_timeout(700)
        try:
            await page.click('[data-testid="toggle-trace-1"]', timeout=5000)
        except Exception:
            await page.click('[data-testid="toggle-trace-0"]', timeout=5000)
        await page.wait_for_timeout(800)
        await page.screenshot(path=str(OUT / "04-trace.png"))
        print("✓ 04-trace.png")

        # 5. Dashboard
        await page.goto(f"{base_url}/dashboard", wait_until="networkidle")
        await page.wait_for_timeout(1800)
        await page.screenshot(path=str(OUT / "05-dashboard.png"))
        print("✓ 05-dashboard.png")

        await browser.close()
    print(f"\nAll done. Files in {OUT}/")


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DEMO_URL", DEFAULT_URL)
    asyncio.run(main(base.rstrip("/")))
