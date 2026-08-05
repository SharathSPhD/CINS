"""Capture the application screenshots that the demo video is built from.

These were previously taken by hand, which meant the video could silently keep
showing a page that had since been rewritten. Driving them from a script keeps
the captures regenerable from the running application, the same discipline the
figures follow.

Requires both dev servers up (see .claude/launch.json):

    backend   .venv/bin/python -m uvicorn app.main:app --app-dir app/backend --port 8000
    frontend  npm --prefix app/frontend run dev

Run:  .venv/bin/python experiments/capture_ui.py [outdir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
SIZE = {"width": 1600, "height": 1000}
SOLVE_MS = 180_000


def _settle(page, ms: int = 900) -> None:
    page.wait_for_timeout(ms)


def _shoot(page, out: Path, name: str) -> None:
    path = out / f"{name}.png"
    page.screenshot(path=str(path))
    print(f"  {name}.png", flush=True)


def _scroll_to(page, text: str) -> bool:
    """Scroll a heading into view so the capture frames that section."""
    # A heading, not any paragraph that happens to contain the words:
    # get_by_text does a case-insensitive substring match, so "Boundary layer"
    # otherwise matches the intro prose above the section and barely scrolls.
    loc = page.get_by_role("heading", name=text).first
    try:
        loc.wait_for(state="visible", timeout=8000)
    except PWTimeout:
        print(f"  ! heading not found: {text}", flush=True)
        return False
    # scroll_into_view_if_needed is a no-op once the element is already partly
    # on screen, which leaves the chart under the fold. Anchor it to the top
    # explicitly, then back off so the heading is not flush against the navbar.
    loc.evaluate("el => el.scrollIntoView({block: 'start', behavior: 'instant'})")
    page.mouse.wheel(0, -80)
    _settle(page, 700)
    return True


def capture(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=SIZE, device_scale_factor=1)
        page.set_default_timeout(30_000)

        # 01 home
        page.goto(BASE, wait_until="networkidle")
        _settle(page)
        _shoot(page, out, "01-home")

        # 02/03 analyze, before and after the solve
        page.goto(f"{BASE}/analyze", wait_until="networkidle")
        _settle(page)
        _shoot(page, out, "02-analyze-form")

        page.get_by_role("button", name="Solve", exact=True).click()
        page.wait_for_selector("text=Boundary-layer distributions", timeout=SOLVE_MS)
        _settle(page, 1500)
        page.mouse.wheel(0, -3000)
        _settle(page, 500)
        _shoot(page, out, "03-analyze-solved")

        if _scroll_to(page, "CST Studio"):
            _shoot(page, out, "03b-analyze-cst")
        if _scroll_to(page, "Boundary-layer distributions"):
            _shoot(page, out, "03c-analyze-bl")

        # 04 inverse
        page.goto(f"{BASE}/inverse", wait_until="networkidle")
        _settle(page)
        _shoot(page, out, "04-inverse")

        # 05/06 flow field, speed then Cp, with the viscous half switched on.
        # The Reynolds box must be filled or the page runs the inviscid field
        # alone and the boundary-layer panels never appear, which is the whole
        # point of showing this page.
        page.goto(f"{BASE}/flowfield", wait_until="networkidle")
        _settle(page)
        try:
            page.get_by_placeholder("1000000").fill("1000000")
        except PWTimeout:
            print("  ! Reynolds field not found", flush=True)
        try:
            page.get_by_role("button", name="Solve", exact=True).click()
        except PWTimeout:
            pass
        page.wait_for_selector("canvas, img", timeout=SOLVE_MS)
        _settle(page, 5000)
        _shoot(page, out, "05-flowfield-speed")

        try:
            page.get_by_role("button", name="Cp contour").click()
            _settle(page, 2500)
        except PWTimeout:
            print("  ! Cp contour toggle not found", flush=True)
        _shoot(page, out, "06-flowfield-cp")

        if _scroll_to(page, "Boundary layer"):
            _settle(page, 1000)
            _shoot(page, out, "06b-flowfield-bl")

        # 07/08 gallery, top then the corpus grid
        page.goto(f"{BASE}/gallery", wait_until="networkidle")
        _settle(page, 2500)
        _shoot(page, out, "07-gallery")
        if _scroll_to(page, "Airfoil corpus"):
            _settle(page, 1200)
            _shoot(page, out, "08-gallery-corpus")

        browser.close()
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("experiments/results/demo/ui")
    print(f"capturing -> {target}", flush=True)
    raise SystemExit(capture(target))
