"""Exercise the narrow History panel in a macOS Tauri build.

This script talks to the test-only embedded WebDriver server. It runs only in
the fork's preview workflow; the fix branch does not include this harness.
"""

import argparse
import base64
import json
import os
import plistlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def request(method, path, payload=None, timeout=15):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:4445{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        result = json.load(response)
    value = result.get("value")
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(f"WebDriver {method} {path}: {value}")
    return value


def execute(session, script):
    return request("POST", f"/session/{session}/execute/sync", {"script": script, "args": []})


def wait_for(predicate, seconds=40):
    deadline = time.monotonic() + seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (OSError, RuntimeError) as error:
            last_error = error
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for app state: {last_error}")


MEASURE = r"""
const panel = document.querySelector('[data-history-panel]');
const filter = panel?.querySelector('.history-filter-scroll');
const search = panel?.querySelector('[data-history-search]');
if (!panel || !filter || !search) return null;
const filterRect = filter.getBoundingClientRect();
const searchRect = search.getBoundingClientRect();
return {
  panelWidth: panel.getBoundingClientRect().width,
  filterHeight: filterRect.height,
  filterLeft: filterRect.left,
  filterTop: filterRect.top,
  filterBottom: filterRect.bottom,
  filterScrollWidth: filter.scrollWidth,
  filterClientWidth: filter.clientWidth,
  searchTop: searchRect.top,
  searchBottom: searchRect.bottom,
  locale: document.documentElement.lang,
  scrollable: filter.classList.contains('history-filter-scroll--scrollable'),
  scrollbarWidth: getComputedStyle(filter).scrollbarWidth
};
"""


def save_screenshot(session, target, errors):
    try:
        encoded = request("GET", f"/session/{session}/screenshot", timeout=30)
        target.write_bytes(base64.b64decode(encoded))
    except (OSError, ValueError, RuntimeError) as error:
        errors.append(f"{target.name}: {error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    info_path = args.app / "Contents" / "Info.plist"
    with info_path.open("rb") as handle:
        executable = plistlib.load(handle)["CFBundleExecutable"]
    binary = args.app / "Contents" / "MacOS" / executable

    env = dict(os.environ, TAURI_WEBDRIVER_PORT="4445", LANG="en_US.UTF-8")
    with (args.output / "app.log").open("w") as app_log:
        app = subprocess.Popen([str(binary)], env=env, stdout=app_log, stderr=subprocess.STDOUT)
        session = None
        results = {"app": str(args.app), "screenshotErrors": []}
        try:
            wait_for(lambda: request("GET", "/status"), 50)
            created = request("POST", "/session", {"capabilities": {"alwaysMatch": {}}})
            session = created["sessionId"]

            def open_history():
                return execute(session, r"""
const button = document.querySelector('button:has(svg.lucide-history)');
if (!button) return false;
if (!document.querySelector('[data-history-panel]')) button.click();
return !!document.querySelector('[data-history-panel]');
""")

            wait_for(open_history)
            for width in (288, 260, 240):
                execute(session, f"""
const panel = document.querySelector('[data-history-panel]');
panel.parentElement.parentElement.style.width = '{width}px';
return panel.getBoundingClientRect().width;
""")
                time.sleep(0.5)
                before = execute(session, MEASURE)
                if before and before["filterScrollWidth"] > before["filterClientWidth"]:
                    break
            else:
                raise AssertionError(f"History filters never overflowed: {before}")

            results["beforeHover"] = before
            save_screenshot(session, args.output / "history-before-hover.png", results["screenshotErrors"])

            # Move a real WebDriver pointer to the bottom of the horizontal filter.
            # On macOS this should reveal the overlay scrollbar, if the runner
            # supports pointer actions in its GUI session.
            x = round(before["filterLeft"] + before["filterClientWidth"] / 2)
            y = round(before["filterBottom"] - 2)
            try:
                request("POST", f"/session/{session}/actions", {
                    "actions": [{"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"},
                                 "actions": [{"type": "pointerMove", "duration": 0, "x": x, "y": y, "origin": "viewport"}]}]
                })
                results["pointerAction"] = "sent"
            except (OSError, RuntimeError) as error:
                results["pointerAction"] = f"unavailable: {error}"
            time.sleep(1)
            after = execute(session, MEASURE)
            results["afterHover"] = after
            save_screenshot(session, args.output / "history-after-hover.png", results["screenshotErrors"])

            assert before["scrollable"] and after["scrollable"], "Filter scrollbar was not active"
            assert before["filterHeight"] >= 43, f"Scrollbar space was not reserved: {before}"
            assert after["filterHeight"] >= 43, f"Scrollbar space collapsed after hover: {after}"
            assert abs(after["searchTop"] - before["searchTop"]) <= 1, (
                f"Search box moved after hovering the scrollbar: {before} -> {after}"
            )
            results["passed"] = True
        except Exception as error:
            results["passed"] = False
            results["error"] = repr(error)
            raise
        finally:
            (args.output / "result.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            if session:
                try:
                    request("DELETE", f"/session/{session}")
                except OSError:
                    pass
            app.terminate()
            try:
                app.wait(timeout=10)
            except subprocess.TimeoutExpired:
                app.kill()


if __name__ == "__main__":
    sys.exit(main())
