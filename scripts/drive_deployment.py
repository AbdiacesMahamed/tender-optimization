"""Drive the deployed Streamlit app with real file uploads and scan for errors.

Unlike check_deployment.py (which just classifies the landing page), this script
uploads GVT + Rate files into the live app, waits for processing, scrolls the
whole page, and reports any Streamlit exception/error blocks plus a full-page
screenshot — so we can confirm the deployed app produces output and isn't hitting
runtime errors further down the page.

Usage:
  python scripts/drive_deployment.py <url> --gvt <gvt.xlsx> --rate <rate.xlsx> \
      [--storage auth.json] [--shot out.png] [--timeout 90]

Streamlit renders the app inside the page (not a cross-origin iframe on
*.streamlit.app), so file_input/text is reachable. If the app is behind viewer
auth, pass --storage with a saved logged-in session (see capture_session()).
"""
from __future__ import annotations

import argparse
import sys
import time

from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Streamlit error/exception surfaces we want to catch anywhere on the page.
ERROR_TEXT = [
    "oh no.", "error running app", "traceback", "exception",
    "modulenotfounderror", "keyerror", "valueerror", "attributeerror",
    "arrowtypeerror", "this app has encountered an error",
]


def _app_frame(page):
    # On *.streamlit.app the actual app runs in a child frame whose URL contains
    # '/~/+/'. The top frame only hosts the chrome. Fall back to the top frame.
    for f in page.frames:
        if "/~/+/" in (f.url or ""):
            return f
    return page.main_frame


def _find_file_inputs(page):
    # Streamlit file_uploader renders a real <input type=file>; there may be
    # several (one per uploader). They live in the app frame.
    return _app_frame(page).query_selector_all('input[type="file"]')


def drive(url, gvt, rate, shot, timeout_s, storage):
    findings = {"page_errors": [], "error_blocks": [], "uploaded": [], "rendered_headers": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx_kwargs = {"viewport": {"width": 1440, "height": 1000}}
        if storage:
            ctx_kwargs["storage_state"] = storage
        ctx = browser.new_context(**ctx_kwargs)
        page = ctx.new_page()
        page.on("pageerror", lambda e: findings["page_errors"].append(str(e)))

        page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
        page.wait_for_timeout(6000)  # let the Streamlit app mount

        inputs = _find_file_inputs(page)
        print(f"file inputs found: {len(inputs)}")
        # Upload GVT to the first, Rate to the second if present.
        try:
            if inputs:
                inputs[0].set_input_files(gvt)
                findings["uploaded"].append(gvt)
                page.wait_for_timeout(4000)
            inputs = _find_file_inputs(page)  # re-query (DOM may rerender)
            if len(inputs) > 1:
                inputs[1].set_input_files(rate)
                findings["uploaded"].append(rate)
        except Exception as e:
            findings["page_errors"].append(f"upload: {e}")

        # Give the app time to process + render scenarios/tables.
        page.wait_for_timeout(12000)
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_s * 1000)
        except Exception:
            pass

        # Scroll the whole page in steps so lazy content renders.
        for _ in range(12):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(800)

        body = ""
        try:
            body = _app_frame(page).inner_text("body", timeout=8000)
        except Exception:
            try:
                body = page.inner_text("body", timeout=8000)
            except Exception:
                pass
        low = body.lower()
        for marker in ERROR_TEXT:
            if marker in low:
                findings["error_blocks"].append(marker)
        for line in body.splitlines():
            s = line.strip()
            if s.startswith(("📊", "📁", "🔁", "🔒", "🚚", "📈", "🤖")) or "Analysis" in s or "Scenario" in s:
                findings["rendered_headers"].append(s[:80])

        try:
            page.screenshot(path=shot, full_page=True)
        except Exception as e:
            findings["page_errors"].append(f"screenshot: {e}")
        browser.close()

    print("=" * 70)
    print(f"uploaded files: {findings['uploaded']}")
    print(f"error markers on page: {sorted(set(findings['error_blocks'])) or 'NONE'}")
    print(f"page errors: {findings['page_errors'] or 'NONE'}")
    print("rendered section headers (sample):")
    for h in dict.fromkeys(findings["rendered_headers"]):
        print("   -", h)
    print(f"full-page screenshot: {shot}")
    print("=" * 70)
    ok = not findings["error_blocks"] and not findings["page_errors"]
    print("VERDICT:", "CLEAN — no errors detected after upload" if ok else "ERRORS DETECTED — inspect screenshot")
    return 0 if ok else 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--gvt", required=True)
    ap.add_argument("--rate", required=True)
    ap.add_argument("--shot", default="deployment_driven.png")
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--storage", default=None)
    args = ap.parse_args()
    return drive(args.url, args.gvt, args.rate, args.shot, args.timeout, args.storage)


if __name__ == "__main__":
    sys.exit(main())
