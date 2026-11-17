"""Same-origin operator dashboard. Device and acknowledgement credentials stay server-side."""

import base64
import hmac
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.domain import credential, validate
from app.handlers import response, secret
from app.store import Store


def forward(path, body, headers):
    """Use the real ingestion/acknowledgement routes; do not bypass the hot path."""
    try:
        with urlopen(Request(os.environ["API_URL"] + path, data=body, headers=headers), timeout=12) as result:
            return response(result.status, json.loads(result.read()))
    except HTTPError as exc:
        return response(exc.code, {"error": "Request rejected by the sensor API"})
    except (URLError, TimeoutError):
        return response(502, {"error": "Sensor API unavailable; retry with the same reading ID"})


def snapshot(configs):
    # Exactly five configured units; no scan, unbounded history query or recurring producer.
    store = Store()
    units = []
    for unit_id, config in configs.items():
        state, _ = store.get("UNIT#" + unit_id)
        state = state or {}
        incidents = {i["incident_id"]: i for i in state.get("recent_incidents", [])}
        if state.get("incident"):
            incidents[state["incident"]["incident_id"]] = state["incident"]
        units.append(
            {
                "unit_id": unit_id,
                "site_id": config["site_id"],
                "threshold": config["threshold"],
                "direction": config["direction"],
                "temperature": state.get("temperature"),
                "observed_at": state.get("last_time") or None,
                "consecutive": state.get("count", 0),
                "history": state.get("history", [])[-20:],
                "incident": state.get("incident"),
                "incidents": sorted(incidents.values(), key=lambda i: i["opened_at"], reverse=True)[:5],
            }
        )
    return {
        "units": units,
        "server_time": int(time.time()),
        "history_limit": 20,
        "ingestion_enabled": os.environ.get("INGESTION_ENABLED", "true") == "true",
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
        if method != "POST" or path not in ("/dashboard/readings", "/dashboard/ack"):
            return response(404, {"error": "Not found"})
        raw = event.get("body", "")
        if len(raw) > 8192:
            return response(413, {"error": "Payload too large"})
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode()
        body = json.loads(raw)
        if method == "POST" and path == "/dashboard/readings":
            reading = validate(body, time.time())
            config = configs.get(reading["unit_id"])
            if not config or reading["site_id"] != config["site_id"]:
                return response(400, {"error": "Unknown sensor"})
            return forward(
                "/readings",
                json.dumps(reading).encode(),
                {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + secret(config["credential_parameter"]),
                },
            )
        if method == "POST" and path == "/dashboard/ack":
            if set(body) != {"unit_id", "incident_id"} or body["unit_id"] not in configs:
                raise ValueError("Invalid incident")
            state, _ = Store().get("UNIT#" + body["unit_id"])
            incident = (state or {}).get("incident")
            if not incident or incident["incident_id"] != body["incident_id"]:
                return response(409, {"error": "This incident is no longer current"})
            if incident["status"] == "resolved":
                return response(409, {"error": "This incident has recovered"})
            if incident["expires_at"] <= time.time():
                return response(403, {"error": "The incident acknowledgement window has expired"})
            params = {"unit": body["unit_id"], "incident": body["incident_id"], "expiry": incident["expires_at"]}
            params["signature"] = credential(
                secret(os.environ["ACK_PARAMETER"]), params["unit"], params["incident"], params["expiry"]
            )
            return forward("/ack", urlencode(params).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
        return response(404, {"error": "Not found"})
    except (ValueError, TypeError, KeyError):
        return response(400, {"error": "Invalid dashboard request"})
