"""React browser checks against a local mocked API. No AWS requests or credentials."""

import copy
import json
import mimetypes
import threading
import time
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TEST_KEY = "local-browser-test"


def fixture():
    now = int(time.time())
    units = []
    for n in range(1, 6):
        freezer = n >= 4
        temperature = -20.0 if freezer else 7.0 if n == 1 else 3.5
        incident = (
            {
                "incident_id": "browser-incident",
                "unit_id": "unit-1",
                "kind": "temperature",
                "status": "open",
                "acknowledged": False,
                "opened_at": now - 50,
                "expires_at": now + 3600,
                "staff_requested": True,
                "staff_requested_at": now - 48,
            }
            if n == 1
            else None
        )
        units.append(
            {
                "unit_id": f"unit-{n}",
                "name": f"Freezer {n - 3:02d}" if freezer else f"Fridge {n:02d}",
                "site_id": "demo-site",
                "kind": "freezer" if freezer else "fridge",
                "threshold": -18 if freezer else 5,
                "direction": "max",
                "interval_s": 30,
                "source": "simulation",
                "enabled": True,
                "revision": 0,
                "temperature": temperature,
                "observed_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                "consecutive": 3 if n == 1 else 0,
                "history": [
                    [
                        datetime.fromtimestamp(now - (19 - i) * 30, timezone.utc).isoformat(),
                        temperature + (i % 3 - 1) * 0.2,
                    ]
                    for i in range(20)
                ],
                "incident": incident,
                "offline_incident": None,
                "incidents": [incident] if incident else [],
                "monitoring": False,
                "monitor_until": None,
                "connection": "online",
            }
        )
    return {
        "units": units,
        "server_time": now,
        "history_limit": 20,
        "ingestion_enabled": True,
        "session": None,
        "report": None,
        "device_endpoint": "https://example.execute-api.eu-north-1.amazonaws.com",
    }


class API(SimpleHTTPRequestHandler):
    state = fixture()
    calls = []
    throttled = set()

    def log_message(self, *_):
        pass

    def end_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        super().end_headers()

    def reply(self, code, body):
        encoded = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def authorized(self):
        if self.headers.get("Authorization") != "Bearer " + TEST_KEY:
            self.reply(401, {"error": "Enter a valid operator access key"})
            return False
        return True

    def do_GET(self):
        if self.path == "/dashboard/state":
            if self.authorized():
                self.state["server_time"] = int(time.time())
                self.reply(200, self.state)
            return
        super().do_GET()

    def do_POST(self):
        if not self.authorized():
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append((self.path, copy.deepcopy(body)))
        unit = next((u for u in self.state["units"] if u["unit_id"] == body.get("unit_id")), None)
        if self.path == "/dashboard/devices":
            unit.update(body)
            unit["revision"] += 1
            if unit["source"] == "physical":
                unit.update(temperature=None, history=[], connection="stale")
        elif self.path == "/dashboard/readings":
            if body["reading_id"] not in self.throttled:
                self.throttled.add(body["reading_id"])
                self.reply(429, {"error": "Test throttling"})
                return
            unit.update(temperature=body["temperature"], observed_at=body["observed_at"])
            unit["history"] = (unit["history"] + [[body["observed_at"], body["temperature"]]])[-20:]
        elif self.path == "/dashboard/ack":
            unit["incident"].update(acknowledged=True, acknowledged_at=int(time.time()))
        elif self.path == "/dashboard/incidents":
            if body["text"] == "conflict":
                self.reply(409, {"error": "Test conflict: refresh and retry"})
                return
            entry = {
                "request_id": body["request_id"],
                "action": body["action"],
                "text": body["text"],
                "at": int(time.time()),
            }
            unit["incident"].setdefault("activity", []).append(entry)
            if body["action"] == "assign":
                unit["incident"]["assignee"] = body["text"]
        elif self.path == "/dashboard/sessions/start":
            now = int(time.time())
            self.state["session"] = {
                "session_id": body["request_id"],
                **body,
                "started_at": now,
                "deadline": now + body["duration_s"],
                "status": "running",
                "max_steps": 100,
                "spacing_s": 6,
                "processed_steps": 2,
                "submitted": 2,
                "skipped": 0,
            }
        elif self.path == "/dashboard/sessions/stop":
            self.state["session"]["status"] = "stopped"
        elif self.path == "/dashboard/reports":
            now = int(time.time())
            self.state["report"] = {
                "request_id": body["request_id"],
                **body,
                "start": now - 3600,
                "end": now,
                "created_at": now,
                "status": "succeeded",
                "query_id": "local-test-query",
                "bytes_scanned": 128000,
                "rows": [
                    {
                        "unit_id": "unit-1",
                        "readings": "100",
                        "minimum": "3.0",
                        "maximum": "8.0",
                        "average": "4.5",
                        "observed_seconds": "570",
                        "excursion_seconds": "180",
                        "unclassified_readings": "0",
                        "incidents": "1",
                        "response_seconds": "40",
                        "recovery_seconds": "240",
                    }
                ],
            }
            self.reply(202, self.state["report"])
            return
        else:
            self.reply(404, {"error": "Unknown test route"})
            return
        self.reply(200, {"status": "saved"})


def main():
    if not (ROOT / "artifacts/web/index.html").exists():
        raise RuntimeError("Run npm run build --prefix app/web before browser checks")
    mimetypes.add_type("application/javascript", ".js")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(API, directory=str(ROOT / "artifacts/web")))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.add_init_script(
                    "document.addEventListener('securitypolicyviolation', e => { window.__csp = (window.__csp || []).concat(e.violatedDirective); });"
                )
                page.goto(f"http://127.0.0.1:{server.server_port}")
                page.get_by_label("Operator access key").fill("wrong")
                page.get_by_role("button", name="Open workspace").click()
                expect(page.get_by_role("alert")).to_contain_text("valid operator")
                page.get_by_label("Operator access key").fill(TEST_KEY)
                page.get_by_role("button", name="Open workspace").click()
                expect(page.locator(".unit-card")).to_have_count(5)
                assert page.evaluate("localStorage.length + sessionStorage.length") == 0
                assert page.locator('input[type="password"]').count() == 0
                page.screenshot(path=str(ROOT / ".local/mvp-desktop.png"), full_page=True)
                page.get_by_role("button", name="Freezers", exact=True).click()
                expect(page.locator(".unit-card")).to_have_count(2)
                page.get_by_role("button", name="All devices", exact=True).click()
                page.locator(".unit-card").first.click()
                expect(page.locator("dialog .recharts-surface")).to_have_count(1)
                page.get_by_label("Send a manual reading").fill("7")
                page.get_by_role("button", name="Send reading", exact=True).click()
                expect(page.get_by_role("status")).to_contain_text("Reading accepted", timeout=10000)
                readings = [body for path, body in API.calls if path == "/dashboard/readings"]
                assert len(readings) == 2 and readings[0] == readings[1]
                page.get_by_role("button", name="Close detail").click()
                page.get_by_role("navigation").get_by_role("button", name="Incidents").click()
                page.locator(".incident-row").first.click()
                page.get_by_role("button", name="Acknowledge", exact=True).click()
                expect(page.locator("dialog")).to_contain_text("Acknowledged")
                expect(page.locator("dialog")).not_to_contain_text("Temperature returned within range")
                page.get_by_label("Details", exact=True).fill("conflict")
                page.get_by_role("button", name="Save activity").click()
                expect(page.locator("dialog [role=alert]")).to_contain_text("Test conflict")
                page.get_by_label("Details", exact=True).fill("Door seal checked")
                page.get_by_role("button", name="Save activity").click()
                expect(page.locator(".timeline")).to_contain_text("Door seal checked")
                page.get_by_label("Activity", exact=True).select_option("assign")
                page.get_by_label("Responder name", exact=True).fill("Night shift")
                page.get_by_role("button", name="Save activity").click()
                expect(page.locator("dialog")).to_contain_text("Assigned responder: Night shift")
                page.get_by_role("button", name="Close detail").click()
                page.get_by_role("navigation").get_by_role("button", name="Overview").click()
                expect(page.locator(".unit-card").first).to_have_class("unit-card attention")
                page.get_by_role("navigation").get_by_role("button", name="Devices").click()
                page.get_by_role("button", name="Configure").nth(1).click()
                page.get_by_label("Device name").fill("Prep fridge")
                page.get_by_label("Data source").select_option("physical")
                page.get_by_role("button", name="Save device settings").click()
                expect(page.locator("dialog h2")).to_contain_text("Prep fridge")
                page.get_by_role("button", name="Close detail").click()
                page.get_by_role("navigation").get_by_role("button", name="Simulation lab").click()
                expect(page.locator(".scenario-card")).to_have_count(6)
                page.screenshot(path=str(ROOT / ".local/mvp-simulation.png"), full_page=True)
                page.get_by_role("button", name="Start simulation", exact=True).click()
                expect(page.get_by_role("button", name="Stop session", exact=True)).to_be_visible()
                start = [body for path, body in API.calls if path == "/dashboard/sessions/start"][0]
                assert start["duration_s"] == 600 and start["interval_s"] == 30 and "unit-2" not in start["units"]
                page.get_by_role("button", name="Stop session", exact=True).click()
                expect(page.locator(".last-run")).to_contain_text("Stopped")
                page.get_by_role("navigation").get_by_role("button", name="Analytics").click()
                page.get_by_role("button", name="Generate report", exact=True).click()
                expect(page.locator("table")).to_contain_text("Fridge 01")
                expect(page.locator(".report-meta")).to_contain_text("Succeeded")
                with page.expect_download() as download:
                    page.get_by_role("button", name="Export CSV", exact=True).click()
                assert download.value.suggested_filename == "coldchain-report.csv"
                page.set_viewport_size({"width": 390, "height": 844})
                for view in ("Overview", "Devices", "Incidents", "Analytics", "Simulation lab"):
                    page.get_by_role("navigation").get_by_role("button", name=view).click()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), view
                page.screenshot(path=str(ROOT / ".local/mvp-mobile.png"), full_page=True)
                page.clock.install()
                page.clock.fast_forward(601000)
                expect(page.get_by_text("Live updates paused after ten minutes.")).to_be_visible()
                page.get_by_role("button", name="Disconnect workspace", exact=True).click()
                expect(page.get_by_role("button", name="Open workspace", exact=True)).to_be_visible()
                assert page.locator(".unit-card").count() == 0
                assert not page.evaluate("window.__csp || []"), page.evaluate("window.__csp")
                assert not errors, errors
                evidence = {
                    "source": "local React production build with mocked API; no AWS",
                    "checks": [
                        "invalid and valid authentication",
                        "no persistent browser credential",
                        "five device cards and filters",
                        "lazy interactive chart",
                        "stable reading ID across 429 retry",
                        "acknowledgement does not recover temperature",
                        "visible modal conflict",
                        "incident notes and assignment",
                        "versioned device configuration",
                        "six simulation scenarios",
                        "backend session start and stop",
                        "on-demand report and CSV",
                        "five mobile views without overflow",
                        "bounded polling",
                        "disconnect data clearing",
                        "CSP",
                    ],
                    "page_errors": errors,
                }
                (ROOT / ".local/mvp-browser-evidence.json").write_text(json.dumps(evidence, indent=2))
                print(json.dumps(evidence))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


if __name__ == "__main__":
    main()
