import json
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app import dashboard
from app.domain import apply_reading, validate


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PARAMETER", "/coldchain-dev/dashboard")
    monkeypatch.setenv("ACK_PARAMETER", "/coldchain-dev/ack")
    monkeypatch.setenv(
        "UNITS",
        json.dumps(
            {
                f"unit-{i}": {
                    "site_id": "demo-site",
                    "threshold": 5,
                    "direction": "max",
                    "credential_parameter": f"/coldchain-dev/devices/unit-{i}",
                }
                for i in range(1, 6)
            }
        ),
    )


def event(path="/dashboard/state", method="GET", body=None, key="operator"):
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method}},
        "headers": {"Authorization": "Bearer " + key},
        "body": json.dumps(body) if body is not None else "",
    }


def sample():
    return {
        "reading_id": "stable-device-id",
        "unit_id": "unit-1",
        "site_id": "demo-site",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "temperature": 7,
        "schema_version": 1,
    }


def test_dashboard_rejects_missing_and_invalid_auth_before_data_access():
    with patch.object(dashboard, "secret", return_value="operator"), patch.object(dashboard, "Store") as store:
        assert dashboard.handler(event(key="wrong"), None)["statusCode"] == 401
        missing = event()
        missing["headers"] = {}
        assert dashboard.handler(missing, None)["statusCode"] == 401
        store.assert_not_called()


def test_snapshot_reads_only_configured_units_and_never_returns_credentials():
    state = {"temperature": 4, "last_time": "2026-11-17T12:00:00Z", "history": [["2026-11-17T12:00:00Z", 4]] * 25}
    with patch.object(dashboard, "secret", return_value="operator"), patch.object(dashboard, "Store") as store:
        store.return_value.get.return_value = (state, 1)
        result = dashboard.handler(event(), None)
        body = json.loads(result["body"])
        assert result["statusCode"] == 200 and len(body["units"]) == 5
        assert len(body["units"][0]["history"]) == 20
        assert store.return_value.get.call_count == 5
        assert {c.args[0] for c in store.return_value.get.call_args_list} == {f"UNIT#unit-{i}" for i in range(1, 6)}
        assert "credential_parameter" not in result["body"] and "operator" not in result["body"]
        assert result["headers"]["cache-control"] == "no-store"


def test_browser_submission_keeps_reading_id_and_uses_real_ingestion_route():
    r = sample()
    with (
        patch.object(
            dashboard, "secret", side_effect=lambda name: "operator" if name.endswith("dashboard") else "device-secret"
        ),
        patch.object(dashboard, "forward", return_value={"statusCode": 202}) as forward,
    ):
        for _ in range(2):
            assert dashboard.handler(event("/dashboard/readings", "POST", r), None)["statusCode"] == 202
        assert all(c.args[0] == "/readings" for c in forward.call_args_list)
        assert all(json.loads(c.args[1])["reading_id"] == r["reading_id"] for c in forward.call_args_list)
        assert forward.call_args.args[2]["Authorization"] == "Bearer device-secret"


@pytest.mark.parametrize(
    "change", [{"unit_id": "unowned"}, {"site_id": "other"}, {"temperature": "7"}, {"schema_version": 2}]
)
def test_browser_cannot_bypass_reading_validation_or_unit_binding(change):
    with patch.object(dashboard, "secret", return_value="operator"), patch.object(dashboard, "forward") as forward:
        assert (
            dashboard.handler(event("/dashboard/readings", "POST", dict(sample(), **change)), None)["statusCode"] == 400
        )
        forward.assert_not_called()


def test_dashboard_ack_is_explicit_post_and_never_returns_signed_credential():
    incident = {"incident_id": "current", "expires_at": int(time.time()) + 100, "status": "escalated"}
    with (
        patch.object(dashboard, "secret", return_value="operator"),
        patch.object(dashboard, "Store") as store,
        patch.object(
            dashboard, "forward", return_value={"statusCode": 200, "body": '{"status":"acknowledged"}'}
        ) as forward,
    ):
        store.return_value.get.return_value = ({"incident": incident}, 1)
        assert dashboard.handler(event("/dashboard/ack"), None)["statusCode"] == 404
        forward.assert_not_called()
        result = dashboard.handler(
            event("/dashboard/ack", "POST", {"unit_id": "unit-1", "incident_id": "current"}), None
        )
        assert result["statusCode"] == 200 and "signature" not in result["body"]
        assert forward.call_args.args[0] == "/ack"
        assert b"signature=" in forward.call_args.args[1]


@pytest.mark.parametrize(
    "incident_id,status,expiry,expected",
    [("old", "open", 100, 409), ("current", "resolved", 100, 409), ("current", "open", -1, 403)],
)
def test_dashboard_refuses_stale_recovered_or_expired_ack(incident_id, status, expiry, expected):
    incident = {"incident_id": "current", "expires_at": int(time.time()) + expiry, "status": status}
    with (
        patch.object(dashboard, "secret", return_value="operator"),
        patch.object(dashboard, "Store") as store,
        patch.object(dashboard, "forward") as forward,
    ):
        store.return_value.get.return_value = ({"incident": incident}, 1)
        result = dashboard.handler(
            event("/dashboard/ack", "POST", {"unit_id": "unit-1", "incident_id": incident_id}), None
        )
        assert result["statusCode"] == expected
        forward.assert_not_called()


def test_forwarding_timeout_is_retryable_without_logging_secrets(monkeypatch):
    monkeypatch.setenv("API_URL", "https://example.execute-api.eu-north-1.amazonaws.com")
    with patch.object(dashboard, "urlopen", side_effect=TimeoutError):
        result = dashboard.forward("/readings", b"{}", {"Authorization": "Bearer never-log-this"})
    assert result["statusCode"] == 502
    assert "never-log-this" not in result["body"]


def test_recent_history_is_bounded_and_ignores_reordered_or_duplicate_readings():
    from simulator.run import readings

    state = None
    for _, r in readings(datetime(2026, 11, 17, tzinfo=timezone.utc), "history", rounds=40, units=1):
        state, _ = apply_reading(state, validate(r), {"direction": "max", "threshold": 5}, 100)
    assert len(state["history"]) == 20
    assert state["temperature"] == state["history"][-1][1]
    after, _ = apply_reading(state, validate(r), {"direction": "max", "threshold": 5}, 100)
    assert after == state
