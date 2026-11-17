from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError

from app.domain import apply_reading, credential, transition, validate, verify_credential
from app.store import Store
from simulator.run import readings

CFG = {"threshold": 5, "direction": "max"}


def reading(n, temp=7):
    return validate(
        {
            "reading_id": f"r{n}",
            "unit_id": "unit-1",
            "site_id": "demo-site",
            "schema_version": 1,
            "temperature": temp,
            "observed_at": f"2026-11-17T10:{n // 2:02}:{n % 2 * 30:02}Z",
        }
    )


def opened():
    state = None
    for n in range(3):
        state, events = apply_reading(state, reading(n), CFG, 100 + n * 30)
    return state


def test_normal_spike_reset_and_recovery():
    state = None
    for n, temp in enumerate([4, 7, 4, 7, 7, 7]):
        state, events = apply_reading(state, reading(n, temp), CFG, 100 + n * 30)
        assert len(events) == (1 if n == 5 else 0)
    assert state["incident"]["status"] == "open"
    state, events = apply_reading(state, reading(6, 4), CFG, 300)
    assert events[0]["type"] == "incident.resolved"
    assert state["count"] == 0


def test_duplicates_stale_and_gap():
    state, _ = apply_reading(None, reading(1), CFG, 100)
    assert apply_reading(state, reading(1), CFG, 101) == (state, [])
    assert apply_reading(state, reading(0), CFG, 101) == (state, [])
    state, _ = apply_reading(state, reading(6), CFG, 200)
    assert state["count"] == 1


def test_freezer_and_minimum_direction():
    state, _ = apply_reading(None, reading(0, -17), {"threshold": -18, "direction": "max"}, 1)
    assert state["count"] == 1
    state, _ = apply_reading(None, reading(0, -21), {"threshold": -20, "direction": "min"}, 1)
    assert state["count"] == 1


def test_escalation_late_ack_recovery_and_expiry():
    state = opened()
    iid = state["incident"]["incident_id"]
    state, events, status = transition(state, iid, "staff", 160)
    assert events[0]["type"] == "notification.staff"
    assert transition(state, iid, "check", 279)[2] == "waiting"
    state, events, status = transition(state, iid, "check", 280)
    assert status == "escalated"
    assert transition(state, iid, "check", 281)[1] == []
    state, events, status = transition(state, iid, "ack", 300)
    assert status == "acknowledged"
    assert transition(state, iid, "ack", 301)[1] == []
    state, _ = apply_reading(state, reading(3, 4), CFG, 302)
    assert transition(state, iid, "check", 400)[2] == "resolved"
    with pytest.raises(ValueError):
        transition(state, iid, "ack", 4000)


def test_recovery_prevents_escalation_and_superseded_workflow():
    state = opened()
    iid = state["incident"]["incident_id"]
    state, _ = apply_reading(state, reading(3, 4), CFG, 170)
    assert transition(state, iid, "check", 300)[1:] == ([], "resolved")
    assert transition(state, "other", "check", 300)[2] == "superseded"


def test_credentials():
    signature = credential("secret", "unit-1", "abc", 1000)
    verify_credential("secret", "unit-1", "abc", "1000", signature, 999)
    for unit, expiry, sig, now in [
        ("unit-2", 1000, signature, 1),
        ("unit-1", 1000, signature, 1000),
        ("unit-1", 1000, "bad", 1),
    ]:
        with pytest.raises(ValueError):
            verify_credential("secret", unit, "abc", expiry, sig, now)


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature", float("nan")),
        ("temperature", True),
        ("schema_version", 2),
        ("observed_at", "2026-11-17T10:00:00"),
        ("unit_id", "<script>"),
    ],
)
def test_invalid(field, value):
    r = dict(reading(0), observed_at="2026-11-17T10:00:00Z")
    r[field] = value
    with pytest.raises(ValueError):
        validate(r)


def test_simulator_is_bounded_and_ids_stable():
    args = datetime(2026, 11, 17, tzinfo=timezone.utc), "run"
    rows = list(readings(*args))
    assert len(rows) == 100
    assert rows == list(readings(*args))
    assert len({r["reading_id"] for _, r in rows}) == 100


def test_transaction_conflict_retries_and_keeps_outbox_atomic():
    from unittest.mock import Mock

    db = Mock()
    db.exceptions.TransactionCanceledException = ClientError
    db.get_item.return_value = {}
    db.transact_write_items.side_effect = [
        ClientError(
            {
                "Error": {"Code": "TransactionCanceledException"},
                "CancellationReasons": [{"Code": "ConditionalCheckFailed"}],
            },
            "TransactWriteItems",
        ),
        {},
    ]
    store = Store(db, "test")
    state = opened()
    result = store.update("unit-1", lambda old: (state, [{"event_id": "id", "type": "incident.opened"}], "done"), "r1")
    assert result == "done"
    assert db.transact_write_items.call_count == 2
    assert len(db.transact_write_items.call_args.kwargs["TransactItems"]) == 4


def test_concurrent_domain_transitions_with_cas():
    # Reference CAS loop: two contenders read the same version; loser recomputes.
    import threading

    state, version, events = opened(), 0, []
    lock = threading.Lock()
    barrier = threading.Barrier(2)
    iid = state["incident"]["incident_id"]

    def run(action):
        nonlocal state, version
        first = True
        while True:
            with lock:
                snapshot, v = state, version
            candidate, emitted, _ = transition(snapshot, iid, action, 300)
            if first:
                barrier.wait()
                first = False
            with lock:
                if v != version:
                    continue
                state, version = candidate, version + 1
                events.extend(emitted)
                return

    with ThreadPoolExecutor(2) as executor:
        list(executor.map(run, ["ack", "check"]))
    assert state["incident"]["acknowledged"]
    assert sum(e["type"] == "incident.escalated" for e in events) <= 1


def test_retry_after_escalation_commit_is_terminal():
    state = opened()
    iid = state["incident"]["incident_id"]
    state, _, _ = transition(state, iid, "check", 300)
    assert transition(state, iid, "check", 301)[1:] == ([], "escalated")


def test_technical_workflow_failure_does_not_ack_or_resolve_incident():
    state = opened()
    iid = state["incident"]["incident_id"]
    state, events, status = transition(state, iid, "failure", 300)
    assert status == "failed" and events[0]["type"] == "workflow.failed"
    assert not state["incident"]["acknowledged"] and state["incident"]["status"] == "open"
    assert transition(state, iid, "failure", 301)[1] == []
