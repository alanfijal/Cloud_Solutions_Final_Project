"""Bounded Step Functions sessions: simulated sensors or physical-device monitoring."""

import copy
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone

from app.domain import ID, event
from app.fleet import Conflict, check_offline, configuration
from app.handlers import log, secret
from app.scenarios import SCENARIOS, temperature
from app.store import Store, client

ACTIVE = "SESSION#active"


def public(session, now=None):
    if not session:
        return None
    result = {k: v for k, v in session.items() if k != "configurations"}
    if (now or int(time.time())) >= result["deadline"] and result["status"] in ("starting", "running", "stopping"):
        result["status"] = "expired"
    return result


def start(body, store=None, now=None):
    now = int(time.time()) if now is None else now
    store = store or Store()
    if set(body) != {"request_id", "mode", "scenario", "units", "duration_s", "interval_s"}:
        raise ValueError("Invalid session settings")
    if not isinstance(body["request_id"], str) or not ID.fullmatch(body["request_id"]):
        raise ValueError("Invalid request ID")
    if body["mode"] not in ("simulation", "monitor") or body["scenario"] not in SCENARIOS:
        raise ValueError("Choose a valid session mode and scenario")
    if type(body["duration_s"]) is not int or not 60 <= body["duration_s"] <= 600:
        raise ValueError("Session duration must be 60–600 seconds")
    if type(body["interval_s"]) is not int or body["interval_s"] not in (10, 30):
        raise ValueError("Use a 10-second demo or 30-second standard interval")
    bases = json.loads(os.environ["UNITS"])
    units = body["units"]
    if (
        not isinstance(units, list)
        or not 1 <= len(units) <= 5
        or len(set(units)) != len(units)
        or any(u not in bases for u in units)
    ):
        raise ValueError("Choose 1–5 configured devices")
    configurations = {}
    for unit in units:
        state, _ = store.get("UNIT#" + unit)
        cfg = configuration(unit, bases[unit], state)
        expected = "simulation" if body["mode"] == "simulation" else "physical"
        if not cfg["enabled"] or cfg["source"] != expected:
            raise Conflict(f"{unit} must be enabled and configured for {expected}")
        configurations[unit] = cfg
    spacing = max(2, math.ceil(body["interval_s"] / len(units))) if body["mode"] == "simulation" else 15
    steps = min(100, body["duration_s"] // spacing)
    request_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def claim(old):
        if old and old["session_id"] == body["request_id"]:
            if old["request_hash"] != request_hash:
                raise Conflict("A request ID cannot be reused with different session settings")
            return old
        if old and old["status"] in ("starting", "running", "stopping") and old["deadline"] > now:
            raise Conflict("Stop the current session before starting another")
        count = old.get("daily_sessions", 0) if old and old.get("day") == now // 86400 else 0
        if count >= 10:
            raise Conflict("The workspace has reached its ten-session daily demo limit")
        return {
            "day": now // 86400,
            "daily_sessions": count + 1,
            "session_id": body["request_id"],
            "request_hash": request_hash,
            "mode": body["mode"],
            "scenario": body["scenario"],
            "units": units,
            "duration_s": body["duration_s"],
            "interval_s": body["interval_s"],
            "spacing_s": spacing,
            "max_steps": steps,
            "started_at": now,
            "deadline": now + body["duration_s"],
            "status": "starting",
            "processed_steps": 0,
            "submitted": 0,
            "skipped": 0,
            "configurations": configurations,
        }

    session = store.mutate(ACTIVE, claim)
    if session["status"] not in ("starting", "running") or session["deadline"] <= now:
        return public(session, now)
    for unit in units:

        def arm(old, unit=unit):
            state = copy.deepcopy(old or {})
            cfg = configuration(unit, bases[unit], state)
            if cfg["revision"] != configurations[unit]["revision"] or cfg["source"] != configurations[unit]["source"]:
                raise Conflict("Device configuration changed while the session was starting")
            if state.get("monitor", {}).get("session_id") != session["session_id"]:
                state["monitor"] = {
                    "session_id": session["session_id"],
                    "started_at": session["started_at"],
                    "until": session["deadline"],
                    "offline_after_s": max(90, cfg["interval_s"] * 3),
                }
            return state, [], "armed"

        store.update(unit, arm)
    # The lease is committed before StartExecution. A failed publication is retried
    # with the same name/input; the lease expires even if the caller disappears.
    try:
        client("stepfunctions").start_execution(
            stateMachineArn=os.environ["SESSION_WORKFLOW"],
            name=session["session_id"],
            input=json.dumps({"session_id": session["session_id"], "step": 0}, sort_keys=True),
        )
    except client("stepfunctions").exceptions.ExecutionAlreadyExists:
        pass

    def running(old):
        if old["session_id"] != session["session_id"]:
            raise Conflict("Session changed")
        return {**old, "status": "running"} if old["status"] == "starting" else old

    return public(store.mutate(ACTIVE, running), now)


def stop(session_id, store=None):
    store = store or Store()

    def stopping(old):
        if not old or old["session_id"] != session_id:
            raise Conflict("This session is no longer current")
        return {**old, "status": "stopping"} if old["status"] in ("starting", "running") else old

    result = store.mutate(ACTIVE, stopping)
    # Disable monitoring immediately; the workflow exits on its next bounded tick.
    finish_units(result, store, int(time.time()))
    return public(result)


def finish_units(session, store, now):
    for unit in session["units"]:

        def disarm(old):
            state = copy.deepcopy(old or {})
            if state.get("monitor", {}).get("session_id") != session["session_id"]:
                return state, [], "superseded"
            state["monitor"]["until"] = min(now, state["monitor"]["until"])
            incident = state.get("offline_incident")
            events = []
            if incident and incident["status"] == "open":
                incident.update(status="closed", closed_at=now, resolution="monitoring_ended")
                events = [{**event("device.monitoring_ended", incident), "occurred_at": now}]
            return state, events, "stopped"

        store.update(unit, disarm)


def tick(payload, context):
    from app.dashboard import forward

    store, now = Store(), int(time.time())
    session, _ = store.get(ACTIVE)
    sid, step = payload["session_id"], int(payload.get("step", 0))
    if not session or session["session_id"] != sid:
        return {"session_id": sid, "step": step, "done": True, "wait_s": 2}
    terminal = (
        session["status"] not in ("starting", "running")
        or now >= session["deadline"]
        or step >= session["max_steps"]
        or payload.get("action") == "finish"
    )
    if terminal:
        finish_units(session, store, now)

        def finish(old):
            if old["session_id"] != sid:
                return old
            return {
                **old,
                "status": "failed"
                if payload.get("action") == "finish"
                else "stopped"
                if old["status"] == "stopping"
                else "completed",
                "ended_at": now,
            }

        store.mutate(ACTIVE, finish)
        log("session_finished", session_id=sid, steps=session["processed_steps"])
        return {"session_id": sid, "step": step, "done": True, "wait_s": 2}
    # Step Functions retries a tick with the same index. Progress is committed only
    # after acceptance; a crash can resend that same reading ID, never invent a new one.
    if step < session["processed_steps"]:
        return {"session_id": sid, "step": session["processed_steps"], "done": False, "wait_s": session["spacing_s"]}
    submitted = skipped = 0
    if session["mode"] == "simulation":
        unit = session["units"][step % len(session["units"])]
        cfg = session["configurations"][unit]
        count = (session["max_steps"] - 1 - session["units"].index(unit)) // len(session["units"]) + 1
        sample = step // len(session["units"])
        scenario = session["scenario"] if unit == session["units"][0] else "normal"
        value = temperature(scenario, sample, count, cfg)
        if value is None:
            skipped = 1
        else:
            # Fixed observation time makes an HTTP/Task retry byte-for-byte stable.
            observed = session["started_at"] + step * session["spacing_s"]
            reading = {
                "reading_id": f"sim_{sid}_{step}",
                "unit_id": unit,
                "site_id": cfg["site_id"],
                "observed_at": datetime.fromtimestamp(observed, timezone.utc).isoformat().replace("+00:00", "Z"),
                "temperature": value,
                "schema_version": 1,
            }
            base = json.loads(os.environ["UNITS"])[unit]
            result = forward(
                "/readings",
                json.dumps(reading).encode(),
                {
                    "Content-Type": "application/json",
                    "X-Coldchain-Source": "simulation",
                    "Authorization": "Bearer " + secret(base["credential_parameter"]),
                },
            )
            if result["statusCode"] != 202:
                raise RuntimeError("Session ingestion failed; retry the same step")
            submitted = 1
    for unit in session["units"]:
        store.update(unit, lambda old, unit=unit: check_offline(old, unit, now))

    def progress(old):
        if old["session_id"] != sid or old["processed_steps"] > step:
            return old
        return {
            **old,
            "processed_steps": step + 1,
            "submitted": old["submitted"] + submitted,
            "skipped": old["skipped"] + skipped,
        }

    store.mutate(ACTIVE, progress)
    log("session_tick", session_id=sid, step=step, submitted=submitted, skipped=skipped)
    return {"session_id": sid, "step": step + 1, "done": False, "wait_s": session["spacing_s"]}
