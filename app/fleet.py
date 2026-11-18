"""Fleet settings and operational changes, serialized with each unit aggregate."""

import copy
import hashlib
import math

from app.domain import ID, event


class Conflict(ValueError):
    """The caller must refresh state before retrying an operational change."""


def configuration(unit, base, state=None):
    kind = "freezer" if base.get("threshold", 5) < 0 else "fridge"
    number = unit.removeprefix("unit-")
    name = (
        f"{kind.title()} {max(1, int(number) - (3 if kind == 'freezer' else 0)):02d}"
        if unit.startswith("unit-") and number.isdigit()
        else unit.replace("-", " ").title()
    )
    defaults = {
        "name": name,
        "site_id": base["site_id"],
        "kind": kind,
        "threshold": base.get("threshold", 5),
        "direction": base.get("direction", "max"),
        "interval_s": 30,
        "source": "simulation",
        "enabled": True,
    }
    return {**defaults, **(state or {}).get("settings", {}), "revision": (state or {}).get("settings_revision", 0)}


def configure(old, unit, base, body, now):
    required = {
        "unit_id",
        "revision",
        "name",
        "site_id",
        "kind",
        "threshold",
        "direction",
        "interval_s",
        "source",
        "enabled",
    }
    if set(body) != required or body["unit_id"] != unit:
        raise ValueError("Provide every device setting")
    if not isinstance(body["name"], str) or not 1 <= len(body["name"].strip()) <= 60:
        raise ValueError("Device name must contain 1–60 characters")
    if not isinstance(body["site_id"], str) or not ID.fullmatch(body["site_id"]):
        raise ValueError("Site ID must use letters, numbers, hyphens or underscores")
    if body["kind"] not in ("fridge", "freezer") or body["direction"] not in ("min", "max"):
        raise ValueError("Invalid device type or comparison")
    if (
        type(body["threshold"]) not in (int, float)
        or not math.isfinite(body["threshold"])
        or not -90 <= body["threshold"] <= 90
    ):
        raise ValueError("Threshold must be between -90 and 90°C")
    if type(body["interval_s"]) is not int or not 10 <= body["interval_s"] <= 300:
        raise ValueError("Reporting interval must be 10–300 seconds")
    if body["source"] not in ("simulation", "physical") or type(body["enabled"]) is not bool:
        raise ValueError("Invalid source or enabled setting")
    state = copy.deepcopy(old or {})
    cfg = configuration(unit, base, state)
    if type(body["revision"]) is not int or body["revision"] != cfg["revision"]:
        raise Conflict("Device settings changed; refresh and try again")
    if state.get("monitor", {}).get("until", 0) > now:
        raise Conflict("Stop the active session before changing this device")
    if (state.get("incident") or {}).get("status") in ("open", "escalated"):
        raise Conflict("Recover the current temperature incident before changing its rule")
    state["settings"] = {k: v for k, v in body.items() if k not in ("unit_id", "revision")}
    state["settings"]["name"] = body["name"].strip()
    state["settings_revision"] = cfg["revision"] + 1
    if body["source"] != cfg["source"] or body["site_id"] != cfg["site_id"]:
        # Keep the replay watermark, but never label simulated history as physical.
        state.update(temperature=None, history=[], last_received_at=0)
    # A rule change starts a new sequence; old samples cannot count under a new rule.
    state["count"] = 0
    e = {
        "event_id": hashlib.sha256(f"config:{unit}:{state['settings_revision']}".encode()).hexdigest(),
        "type": "device.configured",
        "unit_id": unit,
        "occurred_at": now,
        "configuration": configuration(unit, base, state),
    }
    return state, [e], "saved"


def find_incident(state, incident_id):
    for key in ("incident", "offline_incident"):
        incident = (state or {}).get(key)
        if incident and incident["incident_id"] == incident_id:
            return incident
    return next((i for i in (state or {}).get("recent_incidents", []) if i["incident_id"] == incident_id), None)


def annotate(old, body, now):
    if set(body) != {"unit_id", "incident_id", "request_id", "action", "text"}:
        raise ValueError("Invalid incident change")
    if not ID.fullmatch(body["request_id"]) or body["action"] not in ("assign", "note", "corrective"):
        raise ValueError("Invalid incident action")
    text = body["text"]
    limit = 80 if body["action"] == "assign" else 500
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= limit:
        raise ValueError(f"Enter 1–{limit} characters")
    if len(text.encode("utf-8")) > limit or any(ord(c) < 32 and c not in ("\n", "\t") for c in text):
        raise ValueError("Activity exceeds its byte limit or contains control characters")
    state = copy.deepcopy(old or {})
    incident = find_incident(state, body["incident_id"])
    if not incident:
        raise Conflict("Incident is no longer available in recent history")
    if any(n["request_id"] == body["request_id"] for n in incident.get("activity", [])):
        return state, [], "saved"
    if len(incident.get("activity", [])) >= 20:
        raise Conflict("This demo incident has reached its 20-entry activity limit")
    entry = {"request_id": body["request_id"], "action": body["action"], "text": text.strip(), "at": now}
    incident.setdefault("activity", []).append(entry)
    if body["action"] == "assign":
        incident["assignee"] = text.strip()
    # Synchronize a history copy too; the Store persists current and recent incidents.
    state["recent_incidents"] = [
        i for i in state.get("recent_incidents", []) if i["incident_id"] != incident["incident_id"]
    ] + [incident]
    e = event("incident." + body["action"], incident, body["request_id"])
    e.update(occurred_at=now, activity=entry)
    return state, [e], "saved"


def check_offline(old, unit, now):
    state = copy.deepcopy(old or {})
    monitor = state.get("monitor", {})
    if now >= monitor.get("until", 0):
        return state, [], "inactive"
    last = max(state.get("last_received_at", 0), monitor["started_at"])
    if now - last <= monitor["offline_after_s"]:
        return state, [], "online"
    current = state.get("offline_incident")
    if current and current["status"] == "open":
        return state, [], "offline"
    iid = hashlib.sha256(f"offline:{unit}:{monitor['session_id']}:{last}".encode()).hexdigest()[:32]
    incident = {
        "incident_id": iid,
        "unit_id": unit,
        "kind": "sensor_offline",
        "status": "open",
        "acknowledged": False,
        "opened_at": now,
        "expires_at": now + 3600,
        "session_id": monitor["session_id"],
    }
    state["offline_incident"] = incident
    e = event("device.offline", incident)
    e["occurred_at"] = now
    return state, [e], "offline"
