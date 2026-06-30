"""Headless-browser health check for the deployed Streamlit app.

WebFetch/curl can't render the app (no JS, no cookies) and just see the
viewer-login redirect. Playwright drives a real Chromium, so it executes the
page's JavaScript, follows the auth flow as far as an anonymous browser can, and
captures what a human would actually SEE — a screenshot, the visible text, plus
any console errors / failed network requests / uncaught exceptions.

Usage:
    python scripts/check_deployment.py <url> [--shot out.png] [--timeout 60]
    python scripts/check_deployment.py <url> --storage auth.json   # reuse a logged-in session

It classifies the end state as: RUNNING, ERROR (traceback/"Oh no"), LOGIN
(viewer auth wall), SLEEPING (spun down), or LOADING (still spinning), and prints
the evidence behind the call. Exit code 0 = RUNNING, 2 = LOGIN, 3 = anything else.
"""
from __future__ import annotations

import argparse
import sys

from playwright.sync_api import sync_playwright

# Windows consoles default to cp1252 and choke on the emoji/unicode Streamlit
# renders. Force UTF-8 so printing the page text never raises.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# Substrings that, if visible, identify a specific failure/holding state.
ERROR_MARKERS = [
    "oh no.", "error running app", "this app has encountered an error",
    "traceback", "modulenotfounderror", "importerror", "attributeerror",
    "keyerror", "valueerror", "connection error",
]
SLEEP_MARKERS = [
    "zzzz", "is in the oven", "get this app back up", "yes, get this app back up",
    "this app has gone to sleep", "wake", "app is sleeping",
]
LOGIN_MARKERS = [
    "sign in", "log in", "continue with google", "continue with github",
    "you need to sign in", "viewer authentication", "/-/login", "/-/auth",
]
RUNNING_MARKERS = [
    "carrier tender optimization", "upload", "drag and drop", "browse files",
    "select strategy", "constraints", "carrier flip",
]


def classify(url: str, timeout_s: int, shot: str, storage: str | None) -> int:
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx_kwargs = {"viewport": {"width": 1440, "height": 900}}
        if storage:
            ctx_kwargs["storage_state"] = storage
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()

        page.on("console", lambda m: console_errors.append(f"{m.type}: {m.text}")
                 if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("requestfailed",
                lambda r: failed_requests.append(f"{r.method} {r.url} :: {r.failure}"))

        final_url = url
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
            status = resp.status if resp else None
            # Give Streamlit's websocket app time to mount and render.
            page.wait_for_timeout(2000)
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_s * 1000)
            except Exception:
                pass  # networkidle can never settle on a live websocket app — fine
            page.wait_for_timeout(3000)
            final_url = page.url
        except Exception as e:
            status = None
            page_errors.append(f"navigation: {e}")

        # Screenshot + visible text — the ground truth of what's on screen.
        try:
            page.screenshot(path=shot, full_page=True)
        except Exception as e:
            page_errors.append(f"screenshot: {e}")
        try:
            body_text = page.inner_text("body", timeout=5000)
        except Exception:
            body_text = ""
        title = page.title() if page else ""
        browser.close()

    low = body_text.lower()
    fu_low = (final_url or "").lower()

    def hit(markers, hay):
        return [m for m in markers if m in hay]

    err = hit(ERROR_MARKERS, low)
    sleep = hit(SLEEP_MARKERS, low)
    login = hit(LOGIN_MARKERS, low) or hit(LOGIN_MARKERS, fu_low)
    running = hit(RUNNING_MARKERS, low)

    print("=" * 70)
    print(f"URL            : {url}")
    print(f"final URL      : {final_url}")
    print(f"HTTP status    : {status}")
    print(f"page title     : {title!r}")
    print(f"screenshot     : {shot}")
    print(f"visible chars  : {len(body_text)}")
    print("-" * 70)
    print("VISIBLE TEXT (first 1200 chars):")
    print(body_text[:1200] if body_text.strip() else "  <empty>")
    print("-" * 70)
    if page_errors:
        print(f"PAGE ERRORS ({len(page_errors)}):")
        for e in page_errors[:10]:
            print("  -", e)
    if console_errors:
        print(f"CONSOLE error/warn ({len(console_errors)}):")
        for e in console_errors[:10]:
            print("  -", e[:300])
    if failed_requests:
        print(f"FAILED REQUESTS ({len(failed_requests)}):")
        for e in failed_requests[:10]:
            print("  -", e[:300])
    print("=" * 70)

    if err:
        print(f"VERDICT: ERROR — markers: {err}")
        return 3
    if sleep:
        print(f"VERDICT: SLEEPING — markers: {sleep}")
        return 3
    if running:
        print(f"VERDICT: RUNNING — app UI rendered. markers: {running}")
        return 0
    if login:
        print(f"VERDICT: LOGIN WALL — anonymous browser blocked by viewer auth. markers: {login}")
        return 2
    print("VERDICT: UNKNOWN/LOADING — no decisive markers; inspect the screenshot.")
    return 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--shot", default="deployment_screenshot.png")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--storage", default=None,
                    help="Path to a Playwright storage_state JSON (logged-in session)")
    args = ap.parse_args()
    return classify(args.url, args.timeout, args.shot, args.storage)


if __name__ == "__main__":
    sys.exit(main())
