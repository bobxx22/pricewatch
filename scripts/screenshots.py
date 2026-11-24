"""Capture README screenshots of a running dev server (with `manage.py seed_demo` data).

    uv run python scripts/screenshots.py [base_url]

Uses PLAYWRIGHT_CHANNEL (e.g. "chrome") when set, otherwise Playwright's own Chromium.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
SHOTS = (
    # name, path, color scheme, viewport
    ("dashboard", "/", "light", (1280, 1000)),
    ("product", "/products/{lego}/", "light", (1280, 900)),
    ("product-dark", "/products/{lego}/", "dark", (1280, 900)),
    ("mobile", "/?sort=discount", "light", (390, 844)),
)


def main(base_url: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get("PLAYWRIGHT_CHANNEL") or None)
        page = browser.new_page()
        page.goto(f"{base_url}/?q=LEGO")
        href = page.locator("a.product__title").first.get_attribute("href") or ""
        lego = href.strip("/").split("/")[-1]
        for name, path, scheme, (width, height) in SHOTS:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                color_scheme=scheme,
                device_scale_factor=2 if width < 600 else 1,
            )
            shot = context.new_page()
            shot.goto(base_url + path.format(lego=lego), wait_until="networkidle")
            shot.screenshot(path=OUT / f"{name}.png")
            context.close()
            print("saved", OUT / f"{name}.png")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000")
