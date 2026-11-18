"""Authenticated operational API; sensor and incident credentials remain server-side."""

import base64
import hmac
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.domain import credential, validate
from app.fleet import Conflict, annotate, configuration, configure, find_incident
from app.handlers import response, secret
from app.store import Store


def forward(path, body, headers):
    try:
        with urlopen(Request(os.environ["API_URL"] + path, data=body, headers=headers), timeout=12) as result:
            return response(result.status, json.loads(result.read()))
    except HTTPError as exc:
        return response(exc.code, {"error": "Request rejected by the sensor API"})
    except (URLError, TimeoutError):
        return response(502, {"error": "Sensor API unavailable; retry with the same reading ID"})


def snapshot(configs):
    from app.reports import SLOT
    from app.reports import public as report_public
    from app.sessions import ACTIVE
    from app.sessions import public as session_public

    store, now = Store(), int(time.time())
    units = []
    for unit_id, base in configs.items():
        state, _ = store.get("UNIT#" + unit_id)
        state = state or {}
        config = configuration(unit_id, base, state)
        incidents = {i["incident_id"]: i for i in state.get("recent_incidents", [])}
        for key in ("incident", "offline_incident"):
            if state.get(key):
                incidents[state[key]["incident_id"]] = state[key]
        monitor = state.get("monitor", {})
        monitored = now < monitor.get("until", 0)
        units.append(
            {
                "unit_id": unit_id,
                **config,
                "temperature": state.get("temperature"),
                "observed_at": (state.get("last_time") or None) if state.get("temperature") is not None else None,
                "consecutive": state.get("count", 0),
                "history": state.get("history", [])[-20:],
                "incident": state.get("incident"),
                "offline_incident": state.get("offline_incident"),
                "incidents": sorted(incidents.values(), key=lambda i: i["opened_at"], reverse=True)[:5],
                "monitoring": monitored,
                "monitor_until": monitor.get("until"),
                "connection": "disabled"
                if not config["enabled"]
                else "offline"
                if monitored and state.get("offline_incident", {}).get("status") == "open"
                else "online"
                if now - state.get("last_received_at", 0) <= max(90, config["interval_s"] * 3)
                else "stale",
            }
        )
    return {
        "units": units,
        "server_time": now,
        "history_limit": 20,
        "ingestion_enabled": os.environ.get("INGESTION_ENABLED", "true") == "true",
        "session": session_public(store.get(ACTIVE)[0], now),
        "report": report_public(store.get(SLOT)[0]),
        "device_endpoint": os.environ.get("API_URL", ""),
        "limits": {"device_slots": 5, "session_seconds": 600, "session_readings": 100, "reports_per_day": 20},
    }


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "")
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    authorization = headers.get("authorization", "")
    if not authorization or not hmac.compare_digest(
        authorization.encode(), ("Bearer " + secret(os.environ["DASHBOARD_PARAMETER"])).encode()
    ):
        return response(401, {"error": "Enter a valid operator access key"})
    configs = json.loads(os.environ["UNITS"])
    try:
        if method == "GET" and path == "/dashboard/state":
            return response(200, snapshot(configs))
        if method != "POST" or path not in (
            "/dashboard/readings",
            "/dashboard/ack",
            "/dashboard/devices",
            "/dashboard/incidents",
            "/dashboard/sessions/start",
            "/dashboard/sessions/stop",
        ):
            return response(404, {"error": "Not found"})
        raw = event.get("body", "")
        if len(raw) > 8192:
            return response(413, {"error": "Payload too large"})
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode()
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object")
        if path == "/dashboard/sessions/start":
            from app.sessions import start

            return response(202, start(body))
        if path == "/dashboard/sessions/stop":
            from app.sessions import stop

            if set(body) != {"session_id"}:
                raise ValueError("Provide the current session ID")
            return response(202, stop(body["session_id"]))
        unit_id = body.get("unit_id")
        if unit_id not in configs:
            raise ValueError("Unknown sensor")
        if path == "/dashboard/devices":
            result = Store().update(
                unit_id, lambda old: configure(old, unit_id, configs[unit_id], body, int(time.time()))
            )
            return response(200, {"status": result})
        if path == "/dashboard/incidents":
            result = Store().update(unit_id, lambda old: annotate(old, body, int(time.time())))
            return response(200, {"status": result})
        state, _ = Store().get("UNIT#" + unit_id)
        if path == "/dashboard/readings":
            reading = validate(body, time.time())
            config = configuration(unit_id, configs[unit_id], state)
            if not config["enabled"] or config["source"] != "simulation" or reading["site_id"] != config["site_id"]:
                raise Conflict("Manual simulation requires an enabled simulation device with the correct site")
            if state and state.get("monitor", {}).get("until", 0) > time.time():
                raise Conflict("Stop the active session before sending manual readings")
            return forward(
                "/readings",
                json.dumps(reading).encode(),
                {
                    "Content-Type": "application/json",
                    "X-Coldchain-Source": "simulation",
                    "Authorization": "Bearer " + secret(configs[unit_id]["credential_parameter"]),
                },
            )
        if set(body) != {"unit_id", "incident_id"}:
            raise ValueError("Invalid incident")
        incident = find_incident(state, body["incident_id"])
        if not incident or incident["status"] in ("resolved", "closed"):
            raise Conflict("This incident has recovered or is no longer current")
        if incident["expires_at"] <= time.time():
            return response(403, {"error": "The incident acknowledgement window has expired"})
        params = {"unit": unit_id, "incident": incident["incident_id"], "expiry": incident["expires_at"]}
        params["signature"] = credential(
            secret(os.environ["ACK_PARAMETER"]), params["unit"], params["incident"], params["expiry"]
        )
        return forward("/ack", urlencode(params).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
    except Conflict as exc:
        return response(409, {"error": str(exc)})
    except ValueError as exc:
        return response(400, {"error": str(exc) or "Invalid dashboard request"})
    except (TypeError, KeyError):
        return response(400, {"error": "Invalid dashboard request"})
