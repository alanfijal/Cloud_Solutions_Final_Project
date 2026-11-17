"""Exercise the history SQL against a complete bounded demo and retry overlap."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from simulator.run import readings


def test_full_demo_history_keeps_incidents_after_100_readings():
    query = (Path(__file__).resolve().parents[1] / "docs/sql/history.sql").read_text()
    # Athena's equivalent JSON scalar function/database qualifier are the only substitutions.
    query = query.replace("coldchain_dev.events", "events").replace("json_extract_scalar(", "json_extract(")
    db = sqlite3.connect(":memory:")
    db.execute("""CREATE TABLE events (
        event_id TEXT, event_type TEXT, unit_id TEXT, reading_id TEXT,
        incident_id TEXT, observed_at TEXT, temperature REAL, detail TEXT, "$path" TEXT
    )""")
    rows = []
    for _, r in readings(datetime(2026, 11, 17, tzinfo=timezone.utc), "history-test"):
        rows.append(
            (
                r["reading_id"],
                "reading.received",
                r["unit_id"],
                r["reading_id"],
                None,
                r["observed_at"],
                r["temperature"],
                json.dumps(r),
                "batch-a",
            )
        )
    # A changed SQS retry batch can overlap an already stored reading.
    rows.append((*rows[0][:-1], "batch-b"))
    kinds = [
        "incident.opened",
        "notification.staff",
        "incident.escalated",
        "incident.acknowledged",
        "incident.resolved",
    ]
    for n, kind in enumerate(kinds):
        rows.append(
            (
                f"incident-event-{n}",
                kind,
                "unit-1",
                None,
                "incident-1",
                None,
                None,
                json.dumps({"status": "resolved" if kind.endswith("resolved") else "open"}),
                "batch-c",
            )
        )
    db.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)", rows)
    result = db.execute(query).fetchall()
    assert sum(row[0] == "reading.received" for row in result) == 100
    assert {row[0] for row in result if row[0] != "reading.received"} == set(kinds)
    assert len(result) == 105
    db.close()
