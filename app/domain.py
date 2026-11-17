"""Pure domain rules; no AWS calls or credentials."""

import copy
import hashlib
import hmac
import math
import re
from datetime import datetime, timezone

ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def validate(data, now=None):
    if not isinstance(data, dict) or set(data) != {
        "reading_id",
        "unit_id",
        "site_id",
        "observed_at",
        "temperature",
        "schema_version",
    }:
        raise ValueError("invalid fields")
    for key in ("reading_id", "unit_id", "site_id"):
        if not isinstance(data[key], str) or not ID.fullmatch(data[key]):
            raise ValueError("invalid identifier")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported schema")
    t = data["temperature"]
    if type(t) not in (int, float) or not math.isfinite(t) or not -100 <= t <= 100:
        raise ValueError("invalid temperature")
    stamp = data["observed_at"]
    if not isinstance(stamp, str) or not stamp.endswith("Z"):
        raise ValueError("UTC timestamp required")
    dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if dt.utcoffset().total_seconds() != 0:
        raise ValueError("UTC required")
    if now is not None and not -86400 <= (dt.timestamp() - now) <= 60:
        raise ValueError("reading outside ingestion window")
    return dict(data, observed_at=dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"))


def apply_reading(old, reading, config, now):
    """Consecutive means timestamp-increasing accepted readings, <=90 s apart."""
    state = copy.deepcopy(old or {"count": 0, "last_time": "", "incident": None})
    if reading["observed_at"] <= state["last_time"]:
        return state, []
    events = []
    if state["last_time"]:
        gap = (
            datetime.fromisoformat(reading["observed_at"]) - datetime.fromisoformat(state["last_time"])
        ).total_seconds()
        if gap > 90:
            state["count"] = 0
    state["last_time"] = reading["observed_at"]
    high = reading["temperature"] > config["threshold"]
    breach = high if config["direction"] == "max" else reading["temperature"] < config["threshold"]
    state["count"] = min(3, state["count"] + 1) if breach else 0
    incident = state["incident"]
    if breach and state["count"] == 3 and (not incident or incident["status"] == "resolved"):
        iid = hashlib.sha256((reading["unit_id"] + ":" + reading["reading_id"]).encode()).hexdigest()[:32]
        state["incident"] = {
            "incident_id": iid,
            "unit_id": reading["unit_id"],
            "status": "open",
            "acknowledged": False,
            "opened_at": now,
            "expires_at": now + 3600,
            "staff_requested": False,
            "manager_requested": False,
        }
        events.append(event("incident.opened", state["incident"], reading["reading_id"]))
    elif not breach and incident and incident["status"] != "resolved":
        incident["status"] = "resolved"
        incident["resolved_at"] = now
        events.append(event("incident.resolved", incident, reading["reading_id"]))
    return state, events


def event(kind, incident, discriminator=""):
    eid = hashlib.sha256((kind + incident["incident_id"] + discriminator).encode()).hexdigest()
    return {
        "event_id": eid,
        "type": kind,
        "incident_id": incident["incident_id"],
        "unit_id": incident["unit_id"],
        "status": incident["status"],
    }


def transition(old, incident_id, action, now):
    state = copy.deepcopy(old)
    incident = state.get("incident")
    if not incident or incident["incident_id"] != incident_id:
        return state, [], "superseded"
    if action == "failure":
        if incident.get("workflow_outcome") == "failed":
            return state, [], "failed"
        incident["workflow_outcome"] = "failed"
        return state, [event("workflow.failed", incident)], "failed"
    if action not in ("staff", "check", "ack"):
        raise ValueError("unknown incident action")
    if action == "ack":
        if now >= incident["expires_at"]:
            raise ValueError("expired credential")
        if incident["status"] != "resolved" and not incident["acknowledged"]:
            incident["acknowledged"] = True
            incident["acknowledged_at"] = now
            return state, [event("incident.acknowledged", incident)], "acknowledged"
    elif incident["status"] != "resolved" and not incident["acknowledged"]:
        if action == "staff" and not incident["staff_requested"]:
            incident["staff_requested"] = True
            return state, [event("notification.staff", incident)], "waiting"
        if action == "check" and now >= incident["opened_at"] + 120 and not incident["manager_requested"]:
            incident["manager_requested"] = True
            incident["status"] = "escalated"
            return state, [event("incident.escalated", incident)], "escalated"
        if incident["manager_requested"]:
            return state, [], "escalated"
        return state, [], "waiting"
    if incident["status"] == "resolved":
        return state, [], "resolved"
    return state, [], "acknowledged" if incident["acknowledged"] else "waiting"


def credential(secret, unit, incident, expiry):
    payload = f"{unit}:{incident}:{expiry}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify_credential(secret, unit, incident, expiry, signature, now):
    if not ID.fullmatch(unit) or not ID.fullmatch(incident) or int(expiry) <= now:
        raise ValueError("invalid or expired credential")
    if not hmac.compare_digest(credential(secret, unit, incident, int(expiry)), signature):
        raise ValueError("invalid credential")
