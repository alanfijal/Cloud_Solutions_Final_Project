"""Approved AWS rehearsal: <=30 distinct readings, two sessions and one report.

Runs a compressor scenario, then disconnection/reconnection. This sends real SNS
email. Requires explicit live/account flags; never run as a local unit test.
"""

import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aws_local import ACCOUNT, identity


class API:
    def __init__(self, origin, key):
        if origin != "https://dazwahczj9j0k.cloudfront.net":
            raise ValueError("Use the reviewed project's CloudFront origin")
        self.origin, self.key = origin, key

    def call(self, path, body=None):
        encoded = json.dumps(body).encode() if body is not None else None
        for attempt in range(3):
            try:
                with urlopen(
                    Request(
                        self.origin + "/dashboard/" + path,
                        data=encoded,
                        headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"},
                    ),
                    timeout=20,
                ) as result:
                    return json.loads(result.read())
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError(f"Dashboard request failed: {exc.code}, {path}") from None
                time.sleep(1 + attempt)
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise RuntimeError(
                        "Local network unavailable; preserve the session ID and reconnect to inspect its bounded run"
                    ) from None
                time.sleep(1 + attempt)
        raise RuntimeError("HTTP retry limit reached")


def run_session(api, scenario, seconds):
    sid = "rehearsal_" + uuid.uuid4().hex
    started = api.call(
        "sessions/start",
        {
            "request_id": sid,
            "mode": "simulation",
            "scenario": scenario,
            "units": ["unit-1"],
            "duration_s": seconds,
            "interval_s": 30,
        },
    )
    assert started["max_steps"] <= 20
    print(json.dumps({"stage": "session_started", "scenario": scenario, "session_id": sid}), flush=True)
    seen, acked, recovered, incident_id = False, False, False, None
    deadline = time.monotonic() + seconds + 70
    last_progress = 0
    try:
        while time.monotonic() < deadline:
            data = api.call("state")
            unit = next(u for u in data["units"] if u["unit_id"] == "unit-1")
            incident = unit["offline_incident"] if scenario == "disconnect" else unit["incident"]
            session = data["session"]
            if scenario == "disconnect":
                incident = incident if incident and incident.get("session_id") == sid else None
            else:
                incident = incident if incident and incident["opened_at"] >= started["started_at"] else None
            if incident:
                seen, incident_id = True, incident["incident_id"]
                should_ack = scenario == "disconnect" or incident.get("manager_requested")
                if should_ack and not acked and incident["status"] not in ("resolved", "closed"):
                    api.call("ack", {"unit_id": "unit-1", "incident_id": incident_id})
                    acked = True
                    api.call(
                        "incidents",
                        {
                            "unit_id": "unit-1",
                            "incident_id": incident_id,
                            "request_id": uuid.uuid4().hex,
                            "action": "corrective",
                            "text": "Bounded rehearsal: responding to the simulated fault; waiting for fresh-data recovery.",
                        },
                    )
                    print(
                        json.dumps({"stage": "acknowledged", "scenario": scenario, "incident_id": incident_id}),
                        flush=True,
                    )
                if acked and incident["status"] == "resolved":
                    recovered = True
                    break
            if time.monotonic() - last_progress > 30:
                print(
                    json.dumps(
                        {
                            "stage": "waiting",
                            "scenario": scenario,
                            "submitted": session["submitted"],
                            "incident_seen": seen,
                        }
                    ),
                    flush=True,
                )
                last_progress = time.monotonic()
            time.sleep(5)
    finally:
        api.call("sessions/stop", {"session_id": sid})
    for _ in range(12):
        final = api.call("state")["session"]
        if final["status"] not in ("starting", "running", "stopping"):
            break
        time.sleep(5)
    assert final["status"] not in ("starting", "running", "stopping"), "Backend has not finished stopping"
    assert seen and acked and recovered, "Scenario did not complete detection, acknowledgement and fresh-data recovery"
    assert final["submitted"] <= 20
    return {
        "scenario": scenario,
        "session_id": sid,
        "incident_id": incident_id,
        "submitted": final["submitted"],
        "recovered": recovered,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-account", required=True)
    parser.add_argument("--confirm-live", action="store_true", required=True)
    args = parser.parse_args()
    if args.confirm_account != ACCOUNT or not args.confirm_live:
        parser.error("Reviewed deployment and bounded live-test approval are required")
    identity()
    key = Path(".local/dashboard-credential-dev.txt").read_text().strip()
    api = API("https://dazwahczj9j0k.cloudfront.net", key)
    current = api.call("state").get("session")
    if current and current["status"] in ("starting", "running", "stopping"):
        raise RuntimeError("An operator session is already active; it will not be interrupted")
    scenarios = [run_session(api, "compressor", 600), run_session(api, "disconnect", 300)]
    assert sum(s["submitted"] for s in scenarios) <= 30
    time.sleep(10)
    report = api.call("reports", {"request_id": "rehearsal_" + uuid.uuid4().hex, "units": ["unit-1"], "window": "1h"})
    for _ in range(16):
        report = api.call("reports")
        if report and report["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(5)
    assert report and report["status"] == "succeeded" and report["rows"], "Athena report did not return data"
    evidence = {
        "source": "approved AWS rehearsal",
        "scenarios": scenarios,
        "report": report,
        "distinct_reading_limit": 30,
    }
    Path(".local/mvp-live-evidence.json").write_text(json.dumps(evidence, indent=2))
    print(
        json.dumps(
            {
                "stage": "passed",
                "submitted": sum(s["submitted"] for s in scenarios),
                "query_id": report.get("query_id"),
                "bytes_scanned": report.get("bytes_scanned"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
