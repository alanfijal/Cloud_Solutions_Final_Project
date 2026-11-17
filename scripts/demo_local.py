"""Deterministic domain rehearsal. Does not emulate or call AWS services."""

import json
from datetime import datetime, timezone

from app.domain import apply_reading, transition, validate
from simulator.run import readings


def main():
    start = datetime(2026, 11, 17, 10, tzinfo=timezone.utc)
    state = None
    history = []
    for tick, raw in readings(start, "local-rehearsal", units=1):
        now = int(start.timestamp()) + tick * 30
        state, emitted = apply_reading(state, validate(raw), {"threshold": 5, "direction": "max"}, now)
        history.extend(emitted)
        if state["incident"]:
            iid = state["incident"]["incident_id"]
            if emitted and emitted[0]["type"] == "incident.opened":
                state, emitted, _ = transition(state, iid, "staff", now)
                history.extend(emitted)
            state, emitted, _ = transition(state, iid, "check", now)
            history.extend(emitted)
            if tick == 10:
                state, emitted, _ = transition(state, iid, "ack", now)
                history.extend(emitted)
        print(
            json.dumps(
                {
                    "tick": tick,
                    "temperature": raw["temperature"],
                    "consecutive": state["count"],
                    "incident": state["incident"]["status"] if state["incident"] else None,
                }
            )
        )
    print(json.dumps({"events": [e["type"] for e in history], "final": state["incident"]["status"]}))


if __name__ == "__main__":
    main()
