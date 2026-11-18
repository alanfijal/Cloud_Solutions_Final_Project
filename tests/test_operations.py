"""Exercise fleet, session and report behaviour through atomic local service contracts."""

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app import dashboard, handlers, reports, sessions
from app.domain import apply_reading, transition
from app.fleet import Conflict, annotate, check_offline, configuration, configure
from app.scenarios import temperature
from app.store import Store
from tests.test_domain import CFG, opened, reading
from tests.test_store_integration import Database

BASE = {"threshold": 5, "direction": "max", "site_id": "demo-site", "credential_parameter": "/device"}


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("UNITS", json.dumps({"unit-1": BASE}))
    monkeypatch.setenv("SESSION_WORKFLOW", "arn:session")
    monkeypatch.setenv("REPORT_WORKFLOW", "arn:reports")
    monkeypatch.setenv("ATHENA_WORKGROUP", "coldchain-dev")
    monkeypatch.setenv("CATALOG_DATABASE", "coldchain_dev")
    return Store(Database(), "test")


def settings(**changes):
    return {"unit_id": "unit-1", **configuration("unit-1", BASE), **changes}


def session_body(**changes):
    return {
        "request_id": "session-one",
        "mode": "simulation",
        "scenario": "door_open",
        "units": ["unit-1"],
        "duration_s": 600,
        "interval_s": 30,
        **changes,
    }


def states():
    return Mock(exceptions=SimpleNamespace(ExecutionAlreadyExists=type("ExecutionAlreadyExists", (Exception,), {})))


def test_device_edit_is_versioned_and_does_not_expose_the_credential(store):
    store.update("unit-1", lambda old: configure(old, "unit-1", BASE, settings(name="Loading bay"), 10))
    state, _ = store.get("UNIT#unit-1")
    assert state["settings_revision"] == 1 and state["count"] == 0
    assert configuration("unit-1", BASE, state)["name"] == "Loading bay"
    assert "credential_parameter" not in json.dumps(state)
    with pytest.raises(Conflict):
        store.update("unit-1", lambda old: configure(old, "unit-1", BASE, settings(name="Stale edit"), 11))
    assert sum(k.startswith("OUT#") for k in store.db.items) == 1


def test_concurrent_settings_edits_cannot_overwrite_each_other(store):
    def edit(name):
        try:
            return store.update("unit-1", lambda old: configure(old, "unit-1", BASE, settings(name=name), 10))
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(edit, ["A", "B"])) == ["conflict", "saved"]


@pytest.mark.parametrize(
    "change",
    [
        {"threshold": float("nan")},
        {"interval_s": 0},
        {"source": "invented"},
        {"site_id": "bad/site"},
        {"enabled": "false"},
    ],
)
def test_invalid_device_rules_are_rejected(change):
    with pytest.raises(ValueError):
        configure(None, "unit-1", BASE, settings(**change), 10)


def test_active_session_or_incident_prevents_rule_edit():
    for state in [{"monitor": {"until": 100}}, opened()]:
        with pytest.raises(Conflict):
            configure(state, "unit-1", BASE, settings(), 10)


def test_source_switch_clears_simulated_display_and_preserves_replay_watermark():
    old = {"temperature": 4, "history": [["2026-11-17T12:00:00Z", 4]], "last_time": "2026-11-17T12:00:00Z"}
    state, _, _ = configure(old, "unit-1", BASE, settings(source="physical"), 10)
    assert state["temperature"] is None and state["history"] == []
    assert state["last_time"] == old["last_time"]
    after, events = apply_reading(state, reading(1), {**CFG, "revision": 0}, 100)
    assert after == state and events == []


def test_incident_activity_and_ack_survive_concurrent_updates(store):
    store.update("unit-1", lambda _: (opened(), [], "opened"))
    iid = store.get("UNIT#unit-1")[0]["incident"]["incident_id"]
    body = {
        "unit_id": "unit-1",
        "incident_id": iid,
        "request_id": "note-one",
        "action": "corrective",
        "text": "Door closed",
    }

    def note():
        return store.update("unit-1", lambda old: annotate(old, body, 150))

    def ack():
        return store.update("unit-1", lambda old: transition(old, iid, "ack", 151))

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda fn: fn(), [note, ack]))
    note()
    state, _ = store.get("UNIT#unit-1")
    assert state["incident"]["acknowledged"] and len(state["incident"]["activity"]) == 1
    assert store.get("INCIDENT#" + iid)[0]["activity"][0]["text"] == "Door closed"
    assert len(state["recent_incidents"][0]["activity"]) == 1


def test_historical_incident_can_be_assigned_without_modifying_current(store):
    previous = {**opened()["incident"], "incident_id": "previous", "status": "resolved"}
    current = opened()
    current["recent_incidents"] = [previous]
    store.update("unit-1", lambda _: (current, [], "ready"))
    body = {
        "unit_id": "unit-1",
        "incident_id": "previous",
        "request_id": "assign-one",
        "action": "assign",
        "text": "Night shift",
    }
    store.update("unit-1", lambda old: annotate(old, body, 200))
    assert store.get("INCIDENT#previous")[0]["assignee"] == "Night shift"
    assert "assignee" not in store.get("UNIT#unit-1")[0]["incident"]


def test_offline_is_separate_idempotent_and_recovers_only_on_fresh_data(store):
    state = {"monitor": {"session_id": "session-one", "started_at": 100, "until": 700, "offline_after_s": 90}}
    store.update("unit-1", lambda _: (state, [], "armed"))
    for _ in range(2):
        store.update("unit-1", lambda old: check_offline(old, "unit-1", 191))
    state, _ = store.get("UNIT#unit-1")
    assert state["offline_incident"]["status"] == "open" and not state.get("incident")
    assert sum(k.startswith("OUT#") for k in store.db.items) == 1
    after, events = apply_reading(state, reading(0, 4), CFG, 192)
    assert after["offline_incident"]["status"] == "resolved"
    assert [e["type"] for e in events] == ["device.online"]


def test_monitoring_expiry_does_not_create_an_offline_alert():
    state = {"monitor": {"started_at": 10, "until": 30, "offline_after_s": 90}}
    assert check_offline(state, "unit-1", 1000) == (state, [], "inactive")


def test_same_session_start_retries_same_workflow_name_and_input(store):
    sfn = states()
    with patch.object(sessions, "client", return_value=sfn):
        first = sessions.start(session_body(), store, 100)
        second = sessions.start(session_body(), store, 101)
    assert first["session_id"] == second["session_id"]
    assert sfn.start_execution.call_args_list[0] == sfn.start_execution.call_args_list[1]
    assert first["max_steps"] == 20 and first["deadline"] == 700
    with pytest.raises(Conflict):
        sessions.start(session_body(request_id="another"), store, 102)


def test_start_publication_failure_can_be_retried_without_a_new_lease(store):
    sfn = states()
    sfn.start_execution.side_effect = [RuntimeError("network"), {}]
    with patch.object(sessions, "client", return_value=sfn):
        with pytest.raises(RuntimeError):
            sessions.start(session_body(), store, 100)
        assert sessions.start(session_body(), store, 101)["status"] == "running"
    assert store.get(sessions.ACTIVE)[0]["started_at"] == 100


@pytest.mark.parametrize(
    "change", [{"duration_s": 601}, {"units": ["unit-1", "unit-1"]}, {"interval_s": 1}, {"scenario": "unknown"}]
)
def test_invalid_or_unbounded_sessions_are_rejected(store, change):
    with pytest.raises(ValueError):
        sessions.start(session_body(**change), store, 100)


def test_physical_mode_never_generates_readings_and_simulator_cannot_target_physical(store):
    store.update("unit-1", lambda old: configure(old, "unit-1", BASE, settings(source="physical"), 100))
    with pytest.raises(Conflict):
        sessions.start(session_body(), store, 101)
    with patch.object(sessions, "client", return_value=states()):
        sessions.start(session_body(mode="monitor"), store, 101)
    with (
        patch.object(sessions, "Store", return_value=store),
        patch.object(sessions.time, "time", return_value=102),
        patch.object(dashboard, "forward") as forward,
    ):
        sessions.tick({"session_id": "session-one", "step": 0}, None)
        forward.assert_not_called()


def test_tick_http_retry_keeps_stable_reading_bytes_and_does_not_double_count(store):
    with patch.object(sessions, "client", return_value=states()):
        sessions.start(session_body(), store, 100)
    original = store.mutate
    failed = False

    def fail_after_acceptance(key, change):
        nonlocal failed
        if key == sessions.ACTIVE and not failed:
            failed = True
            raise RuntimeError("crash before progress commit")
        return original(key, change)

    captured = []

    def accept(path, body, headers):
        captured.append(json.loads(body))
        return {"statusCode": 202}

    with (
        patch.object(sessions, "Store", return_value=store),
        patch.object(sessions, "secret", return_value="never-log"),
        patch.object(sessions.time, "time", return_value=101),
        patch.object(dashboard, "forward", side_effect=accept),
        patch.object(store, "mutate", side_effect=fail_after_acceptance),
    ):
        with pytest.raises(RuntimeError):
            sessions.tick({"session_id": "session-one", "step": 0}, None)
        sessions.tick({"session_id": "session-one", "step": 0}, None)
        sessions.tick({"session_id": "session-one", "step": 0}, None)
    assert len(captured) == 2 and captured[0] == captured[1]
    assert store.get(sessions.ACTIVE)[0]["submitted"] == 1


def test_stop_disarms_monitoring_and_prevents_future_ticks(store):
    with patch.object(sessions, "client", return_value=states()):
        sessions.start(session_body(), store, 100)
    with patch.object(sessions.time, "time", return_value=200):
        sessions.stop("session-one", store)
    assert store.get("UNIT#unit-1")[0]["monitor"]["until"] == 200
    with (
        patch.object(sessions, "Store", return_value=store),
        patch.object(sessions.time, "time", return_value=201),
        patch.object(dashboard, "forward") as forward,
    ):
        assert sessions.tick({"session_id": "session-one", "step": 1}, None)["done"]
        forward.assert_not_called()
    assert store.get(sessions.ACTIVE)[0]["status"] == "stopped"


def test_deadline_stops_even_when_ui_is_gone(store):
    with patch.object(sessions, "client", return_value=states()):
        sessions.start(session_body(), store, 100)
    with (
        patch.object(sessions, "Store", return_value=store),
        patch.object(sessions.time, "time", return_value=700),
        patch.object(dashboard, "forward") as forward,
    ):
        assert sessions.tick({"session_id": "session-one", "step": 1}, None)["done"]
        forward.assert_not_called()


def test_failure_scenarios_are_repeatable_recover_and_distinguish_a_spike():
    for scenario in ("door_open", "compressor", "warming"):
        values = [temperature(scenario, i, 20, CFG) for i in range(20)]
        assert values == [temperature(scenario, i, 20, CFG) for i in range(20)]
        assert values[0] < 5 and values[-1] < 5
        assert sum(v > 5 for v in values) >= 3
    assert sum(temperature("spike", i, 20, CFG) > 5 for i in range(20)) == 1
    assert any(temperature("disconnect", i, 20, CFG) is None for i in range(20))


def test_report_query_rejects_identifiers_and_does_not_interpolate_user_sql(store):
    with pytest.raises(ValueError):
        reports.sql(["unit-1'; DROP TABLE events"], 0, 10)
    query = reports.sql(["unit-1"], 100, 200)
    assert "row_number()" in query and "greatest(90, interval_s * 3)" in query
    assert "threshold IS NOT NULL" in query and "LIMIT 5" in query


def test_reports_serialize_and_retry_same_request_then_reuse_fresh_results(store):
    body = {"request_id": "report-one", "units": ["unit-1"], "window": "1h"}
    sfn = states()
    with patch.object(reports, "client", return_value=sfn):
        reports.start(body, store, 100)
        reports.start(body, store, 101)
        with pytest.raises(Conflict):
            reports.start({**body, "request_id": "report-two"}, store, 102)
        store.mutate(reports.SLOT, lambda old: {**old, "status": "succeeded"})
        cached = reports.start({**body, "request_id": "report-two"}, store, 103)
    assert cached["request_id"] == "report-one" and sfn.start_execution.call_count == 2
    assert store.get(reports.SLOT)[0]["daily_count"] == 1


def test_report_daily_limit_is_enforced_atomically(store):
    store.mutate(
        reports.SLOT,
        lambda _: {
            "request_id": "old",
            "request_hash": "old",
            "status": "succeeded",
            "created_at": 1,
            "day": 0,
            "daily_count": 20,
        },
    )
    with pytest.raises(Conflict, match="20-report"):
        reports.start({"request_id": "new", "units": ["unit-1"], "window": "1h"}, store, 1000)


def test_report_worker_persists_query_and_cancels_at_deadline(store):
    body = {"request_id": "report-one", "units": ["unit-1"], "window": "1h"}
    with patch.object(reports, "client", return_value=states()):
        reports.start(body, store, 100)
    athena = Mock()
    athena.start_query_execution.return_value = {"QueryExecutionId": "query-one"}
    athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "RUNNING"}}}
    with patch.object(reports, "client", return_value=athena):
        assert not reports.advance({"request_id": "report-one", "poll": 0}, store=store, now=101)["done"]
        reports.advance({"request_id": "report-one", "poll": 1}, store=store, now=102)
        assert reports.advance({"request_id": "report-one", "poll": 2}, store=store, now=160)["done"]
    assert athena.start_query_execution.call_count == 1
    athena.stop_query_execution.assert_called_once_with(QueryExecutionId="query-one")
    assert store.get(reports.SLOT)[0]["status"] == "cancelled"


def test_report_results_have_scan_evidence_and_no_header_row(store):
    with patch.object(reports, "client", return_value=states()):
        reports.start({"request_id": "report-one", "units": ["unit-1"], "window": "1h"}, store, 100)
    athena = Mock()
    athena.start_query_execution.return_value = {"QueryExecutionId": "q"}
    athena.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": "SUCCEEDED"}, "Statistics": {"DataScannedInBytes": 1000}}
    }
    athena.get_query_results.return_value = {
        "ResultSet": {
            "ResultSetMetadata": {"ColumnInfo": [{"Name": "unit_id"}, {"Name": "readings"}]},
            "Rows": [
                {"Data": [{"VarCharValue": "unit_id"}, {"VarCharValue": "readings"}]},
                {"Data": [{"VarCharValue": "unit-1"}, {"VarCharValue": "3"}]},
            ],
        }
    }
    with patch.object(reports, "client", return_value=athena):
        assert reports.advance({"request_id": "report-one"}, store=store, now=101)["done"]
    result = reports.public(store.get(reports.SLOT)[0])
    assert result["rows"] == [{"unit_id": "unit-1", "readings": "3"}]
    assert result["bytes_scanned"] == 1000 and "daily_count" not in result


def test_configuration_outbox_is_valid_without_an_incident_id():
    e = {"type": "device.configured", "unit_id": "unit-1", "event_id": "config-one"}
    record = {
        "eventName": "INSERT",
        "dynamodb": {"NewImage": {"pk": {"S": "OUT#config-one"}, "payload": {"S": json.dumps(e)}}},
    }
    with patch.object(handlers, "publish") as publish:
        handlers.outbox({"Records": [record]}, None)
        publish.assert_called_once_with(e)


def test_sessions_have_a_daily_limit_even_with_accidental_restarts(store):
    old = {
        "session_id": "old",
        "request_hash": "old",
        "status": "completed",
        "deadline": 2,
        "day": 0,
        "daily_sessions": 10,
    }
    store.mutate(sessions.ACTIVE, lambda _: old)
    with pytest.raises(Conflict, match="ten-session"):
        sessions.start(session_body(), store, 100)


def test_old_gateway_backfill_does_not_change_present_device_health(store, monkeypatch):
    from datetime import datetime, timezone

    payload = {
        **reading(0, 20),
        "observed_at": datetime.fromtimestamp(100, timezone.utc).isoformat().replace("+00:00", "Z"),
        "configuration": {**CFG, "interval_s": 30},
        "occurred_at": 500,
    }
    with patch.object(handlers, "Store", return_value=store):
        assert handlers.detector(
            {"Records": [{"messageId": "old", "body": json.dumps({"detail": payload})}]}, None
        ) == {"batchItemFailures": []}
    assert store.get("UNIT#unit-1")[0] is None


def test_gateway_persists_before_sending_and_reuses_bytes_on_network_retry(tmp_path):
    from urllib.error import URLError

    from simulator.device import Gateway

    spool = tmp_path / "gateway.sqlite"
    gateway = Gateway("https://api.example.com", "unit-1", "demo-site", "device-key", spool)
    rid = gateway.enqueue(4)
    gateway.close()
    gateway = Gateway("https://api.example.com", "unit-1", "demo-site", "device-key", spool)
    result = Mock(status=202)
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    with (
        patch.object(gateway.opener, "open", side_effect=[URLError("offline"), result]) as send,
        patch("simulator.device.time.sleep"),
    ):
        assert gateway.flush(1) == 1
        bodies = [c.args[0].data for c in send.call_args_list]
        assert bodies[0] == bodies[1] and json.loads(bodies[0])["reading_id"] == rid
    assert spool.stat().st_mode & 0o777 == 0o600
    assert gateway.db.execute("SELECT count(*) FROM readings").fetchone()[0] == 0
    gateway.close()


def test_gateway_has_finite_retries_and_keeps_unsent_measurement(tmp_path):
    from urllib.error import URLError

    from simulator.device import Gateway

    gateway = Gateway("https://api.example.com", "unit-1", "demo-site", "device-key", tmp_path / "gateway.sqlite")
    gateway.enqueue(4)
    with (
        patch.object(gateway.opener, "open", side_effect=URLError("offline")) as send,
        patch("simulator.device.time.sleep"),
    ):
        with pytest.raises(RuntimeError, match="retained"):
            gateway.flush()
        assert send.call_count == 3
    assert gateway.db.execute("SELECT count(*) FROM readings").fetchone()[0] == 1
    with pytest.raises(ValueError):
        gateway.flush(101)
    gateway.close()


def test_gateway_refuses_plaintext_and_redirects(tmp_path):
    from simulator.device import Gateway, NoRedirect

    with pytest.raises(ValueError):
        Gateway("http://api.example.com", "unit-1", "demo-site", "device-key", tmp_path / "gateway.sqlite")
    with pytest.raises(ValueError):
        NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example.com")


def test_abandoned_report_start_is_recoverable_after_lease_expiry(store):
    body = {"request_id": "first", "units": ["unit-1"], "window": "1h"}
    sfn = states()
    with patch.object(reports, "client", return_value=sfn):
        reports.start(body, store, 100)
        fresh = reports.start({**body, "request_id": "second"}, store, 161)
    assert fresh["request_id"] == "second" and fresh["status"] == "queued"
    assert store.get(reports.SLOT)[0]["daily_count"] == 2


def test_unicode_activity_is_bounded_by_bytes_and_control_characters_are_rejected():
    state = opened()
    body = {
        "unit_id": "unit-1",
        "incident_id": state["incident"]["incident_id"],
        "request_id": "note",
        "action": "note",
    }
    for text in ["\x01" * 100, "\u03b1" * 500]:
        with pytest.raises(ValueError):
            annotate(state, {**body, "text": text}, 200)


def test_completed_workflow_id_is_not_misreported_as_a_new_running_session(store):
    sfn = states()
    sfn.start_execution.side_effect = sfn.exceptions.ExecutionAlreadyExists("used")
    with patch.object(sessions, "client", return_value=sfn):
        with pytest.raises(Conflict, match="already used"):
            sessions.start(session_body(), store, 100)
    assert store.get(sessions.ACTIVE)[0]["status"] == "failed"
    assert store.get("UNIT#unit-1")[0]["monitor"]["until"] == 100


def test_completed_report_id_releases_the_lease_with_an_explicit_error(store):
    sfn = states()
    sfn.start_execution.side_effect = sfn.exceptions.ExecutionAlreadyExists("used")
    with patch.object(reports, "client", return_value=sfn):
        with pytest.raises(Conflict, match="already used"):
            reports.start({"request_id": "old", "units": ["unit-1"], "window": "1h"}, store, 100)
    assert store.get(reports.SLOT)[0]["status"] == "failed"
