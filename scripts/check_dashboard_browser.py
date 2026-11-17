"""Browser regression checks with a local static server and mocked API; no AWS calls."""

import copy
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def fixtures():
    now = int(time.time())
    incident = {
        "incident_id": "fixture-incident",
        "unit_id": "unit-1",
        "status": "open",
        "acknowledged": False,
        "opened_at": now - 60,
        "expires_at": now + 3600,
    }
    units = []
    for i in range(1, 6):
        value = 7 if i == 1 else -20 if i % 2 == 0 else 4
        history = [
            [time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - (19 - n) * 30)), value - 1 + n % 3 * 0.5]
            for n in range(20)
        ]
        units.append(
            {
                "unit_id": f"unit-{i}",
                "site_id": "demo-site",
                "threshold": -18 if i % 2 == 0 else 5,
                "direction": "max",
                "temperature": value,
                "observed_at": history[-1][0],
                "consecutive": 3 if i == 1 else 0,
                "history": history,
                "incident": incident if i == 1 else None,
                "incidents": [incident] if i == 1 else [],
            }
        )
    return {"units": units, "server_time": now, "ingestion_enabled": True}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def end_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
        )
        super().end_headers()


def main():
    from playwright.sync_api import expect, sync_playwright

    root = Path(__file__).resolve().parents[1]
    output = root / ".local"
    output.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root / "app/web")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state = fixtures()
    submitted, errors = [], []
    should_throttle = [True]

    def route(request_route):
        request = request_route.request
        if request.headers.get("authorization") != "Bearer fixture-access":
            request_route.fulfill(status=401, json={"error": "Enter a valid operator access key"})
        elif request.url.endswith("/state"):
            request_route.fulfill(json=copy.deepcopy(state), headers={"cache-control": "no-store"})
        elif request.url.endswith("/readings"):
            submitted.append(request.post_data_json)
            if should_throttle[0]:
                should_throttle[0] = False
                request_route.fulfill(status=429, json={"error": "Transient throttle"})
            else:
                request_route.fulfill(status=202, json={"reading_id": request.post_data_json["reading_id"]})
        elif request.url.endswith("/ack"):
            state["units"][0]["incident"]["acknowledged"] = True
            request_route.fulfill(json={"status": "acknowledged"})
        else:
            request_route.fulfill(status=404, json={"error": "Not found"})

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if "Content Security Policy" in message.text else None,
            )
            page.route("**/dashboard/**", route)
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.locator("#access-key").fill("wrong-key")
            page.locator("#connect").click()
            expect(page.locator("#login-error")).to_contain_text("rejected")
            page.locator("#access-key").fill("fixture-access")
            page.locator("#connect").click()
            expect(page.locator("#login")).not_to_be_visible()
            expect(page.locator(".unit-card")).to_have_count(5)
            assert page.evaluate("localStorage.length + sessionStorage.length") == 0
            assert page.locator("#access-key").input_value() == ""
            page.screenshot(path=str(output / "dashboard-desktop.png"), full_page=True)
            page.get_by_role("button", name="Freezers", exact=True).click()
            expect(page.locator(".unit-card")).to_have_count(2)
            page.get_by_role("button", name="All units", exact=True).click()
            page.get_by_role("button", name="View Fridge 01 temperature history", exact=True).click()
            expect(page.locator("#history-view")).to_be_visible()
            expect(page.locator(".large-chart")).to_be_visible()
            with page.expect_download() as download:
                page.locator("#export-history").click()
            assert download.value.suggested_filename == "unit-1-temperature.csv"
            page.locator(".nav-item[data-view=incidents]").click()
            page.locator("#all-incidents button[data-ack]").click()
            expect(page.locator("#all-incidents")).to_contain_text("Acknowledged")
            page.locator(".nav-item[data-view=overview]").click()
            expect(page.locator(".unit-card.acknowledged.alert")).to_have_count(1)
            page.locator("#manual-temperature").fill("7")
            page.locator("#send-reading").click()
            expect(page.locator("#manual-status")).to_contain_text("accepted", timeout=10000)
            assert len(submitted) == 2 and submitted[0] == submitted[1]
            page.set_viewport_size({"width": 390, "height": 844})
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(path=str(output / "dashboard-mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Mobile layout overflows"
            page.clock.install()
            page.locator("#start-demo").click()
            page.clock.run_for(100)
            expect(page.locator("#demo-count")).to_have_text("1 / 100")
            page.locator("#stop-demo").click()
            sent = len(submitted)
            page.clock.fast_forward(60000)
            assert len(submitted) == sent, "Stopped demo continued sending"
            page.locator("#start-demo").click()
            page.clock.run_for(100)
            expect(page.locator("#demo-count")).to_have_text("1 / 100")
            page.clock.fast_forward(600001)
            expect(page.locator("#stop-demo")).not_to_be_visible()
            sent = len(submitted)
            page.clock.fast_forward(60000)
            assert len(submitted) == sent, "Expired demo continued sending"
            expect(page.locator("#auto-refresh-status")).to_contain_text("paused")
            page.locator("#disconnect").click()
            expect(page.locator("#login")).to_be_visible()
            expect(page.locator(".unit-card")).to_have_count(0)
            assert not errors, errors
            browser.close()
            print(
                json.dumps(
                    {
                        "browser_checks": "passed",
                        "covered": [
                            "login rejection",
                            "private key held only in memory",
                            "five units",
                            "filters",
                            "chart",
                            "CSV export",
                            "acknowledgement",
                            "stable reading ID across HTTP retry",
                            "mobile layout",
                            "stop control",
                            "simulation deadline",
                            "polling deadline",
                            "disconnect",
                            "CSP",
                        ],
                        "screenshots": [".local/dashboard-desktop.png", ".local/dashboard-mobile.png"],
                    }
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
