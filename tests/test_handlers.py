import json
from unittest.mock import Mock, patch

from app import handlers
from app.domain import credential
from app.store import Store
from tests.test_store_integration import Database


def test_partial_batch_failure():
    def process(record):
        if record["messageId"] == "bad":
            raise RuntimeError("poison")

    assert handlers.batch({"Records": [{"messageId": "good"}, {"messageId": "bad"}]}, process) == {
        "batchItemFailures": [{"itemIdentifier": "bad"}]
    }


def test_partial_publication_failure(monkeypatch):
    import pytest

    monkeypatch.setenv("BUS", "test")
    with patch.object(handlers, "client") as client:
        client.return_value.put_events.return_value = {
            "FailedEntryCount": 1,
            "Entries": [{"ErrorCode": "ThrottlingException"}],
        }
        with pytest.raises(RuntimeError):
            handlers.publish({"type": "reading.received"})


def test_auth_and_invalid_input(monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setenv("UNITS", json.dumps({"unit-1": {"site_id": "demo-site", "credential_parameter": "/device"}}))
    reading = {
        "unit_id": "unit-1",
        "site_id": "demo-site",
        "reading_id": "r1",
        "schema_version": 1,
        "temperature": 4,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    with (
        patch.object(handlers, "Store", return_value=Store(Database(), "test")),
        patch.object(handlers, "secret", return_value="secret"),
        patch.object(handlers, "publish") as publish,
    ):
        assert handlers.ingest({"body": "{}"}, None)["statusCode"] == 400
        assert handlers.ingest({"body": json.dumps(reading)}, None)["statusCode"] == 401
        assert (
            handlers.ingest({"body": json.dumps(reading), "headers": {"Authorization": "Bearer secret"}}, None)[
                "statusCode"
            ]
            == 202
        )
        publish.assert_called_once()


def test_get_does_not_ack_and_post_does(monkeypatch):
    monkeypatch.setenv("ACK_PARAMETER", "/ack")
    expiry = 9999999999
    params = {
        "unit": "unit-1",
        "incident": "abc",
        "expiry": str(expiry),
        "signature": credential("secret", "unit-1", "abc", expiry),
    }
    from urllib.parse import urlencode

    with patch.object(handlers, "secret", return_value="secret"), patch.object(handlers, "Store") as store:
        store.return_value.update.return_value = "acknowledged"
        event = {"requestContext": {"http": {"method": "GET"}}, "queryStringParameters": params}
        assert handlers.ack(event, None)["statusCode"] == 200
        store.return_value.update.assert_not_called()
        event = {"requestContext": {"http": {"method": "POST"}}, "body": urlencode(params)}
        assert handlers.ack(event, None)["statusCode"] == 200
        store.return_value.update.assert_called_once()
        event["body"] = urlencode(dict(params, expiry="1"))
        assert handlers.ack(event, None)["statusCode"] == 403


def test_stream_retries_failure_and_stable_workflow_name(monkeypatch):
    monkeypatch.setenv("WORKFLOW", "arn:test")
    e = {"type": "incident.opened", "incident_id": "abc", "unit_id": "unit-1", "event_id": "evt"}
    record = {
        "eventName": "INSERT",
        "dynamodb": {"NewImage": {"pk": {"S": "OUT#evt"}, "payload": {"S": json.dumps(e)}}},
    }
    client = Mock()
    with patch.object(handlers, "publish"), patch.object(handlers, "client", return_value=client):
        handlers.outbox({"Records": [record]}, None)
        handlers.dispatch({"detail": e}, None)
        handlers.dispatch({"detail": e}, None)
    assert [c.kwargs["name"] for c in client.start_execution.call_args_list] == ["abc", "abc"]


def test_ingest_event_round_trips_through_detector(monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setenv(
        "UNITS",
        json.dumps(
            {"unit-1": {"site_id": "demo-site", "credential_parameter": "/device", "threshold": 5, "direction": "max"}}
        ),
    )
    r = {
        "unit_id": "unit-1",
        "site_id": "demo-site",
        "reading_id": "r1",
        "schema_version": 1,
        "temperature": 7,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    from app.store import Store
    from tests.test_store_integration import Database

    database = Database()
    with (
        patch.object(handlers, "Store", return_value=Store(Database(), "test")),
        patch.object(handlers, "secret", return_value="secret"),
        patch.object(handlers, "publish") as publish,
    ):
        assert (
            handlers.ingest({"body": json.dumps(r), "headers": {"authorization": "Bearer secret"}}, None)["statusCode"]
            == 202
        )
        detail = publish.call_args.args[0]
    with patch.object(handlers, "Store", return_value=Store(database, "test")):
        sqs = {"Records": [{"messageId": "one", "body": json.dumps({"detail": detail})}]}
        assert handlers.detector(sqs, None) == {"batchItemFailures": []}
        assert handlers.detector(sqs, None) == {"batchItemFailures": []}
    assert Store(database, "test").get("UNIT#unit-1")[0]["count"] == 1


def test_stream_publication_failure_remains_retryable():
    import pytest

    e = {"type": "incident.opened", "incident_id": "i", "event_id": "e"}
    records = [
        {"eventName": "INSERT", "dynamodb": {"NewImage": {"pk": {"S": "OUT#e"}, "payload": {"S": json.dumps(e)}}}}
    ]
    with patch.object(handlers, "publish", side_effect=RuntimeError("partial failure")):
        with pytest.raises(RuntimeError):
            handlers.outbox({"Records": records}, None)


def test_dispatch_suppresses_notification_after_recovery(monkeypatch):
    from tests.test_domain import opened

    state = opened()
    state["incident"]["status"] = "resolved"
    e = {
        "type": "incident.escalated",
        "incident_id": state["incident"]["incident_id"],
        "unit_id": "unit-1",
        "event_id": "e",
    }
    with patch.object(handlers, "Store") as store, patch.object(handlers, "client") as client:
        store.return_value.get.return_value = (state, 1)
        handlers.dispatch({"detail": e}, None)
        client.assert_not_called()


def test_lake_microbatch_and_partial_failure(monkeypatch):
    from botocore.exceptions import ClientError

    monkeypatch.setenv("LAKE", "lake")
    s3 = Mock()
    s3.exceptions.ClientError = ClientError
    good = {"messageId": "good", "body": json.dumps({"detail": {"type": "reading.received", "event_id": "r1"}})}
    bad = {"messageId": "bad", "body": "bad-json"}
    with patch.object(handlers, "client", return_value=s3):
        assert handlers.lake({"Records": [good, bad]}, None) == {"batchItemFailures": [{"itemIdentifier": "bad"}]}
        assert s3.put_object.call_count == 1
        assert s3.put_object.call_args.kwargs["IfNoneMatch"] == "*"
        s3.put_object.side_effect = ClientError({"Error": {"Code": "InternalError"}}, "PutObject")
        result = handlers.lake({"Records": [good, bad]}, None)
        assert {x["itemIdentifier"] for x in result["batchItemFailures"]} == {"good", "bad"}
        s3.put_object.side_effect = ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        assert handlers.lake({"Records": [good]}, None) == {"batchItemFailures": []}


def test_pause_ingestion_without_credentials_or_traffic(monkeypatch):
    monkeypatch.setenv("INGESTION_ENABLED", "false")
    with patch.object(handlers, "publish") as publish:
        assert handlers.ingest({}, None)["statusCode"] == 503
        publish.assert_not_called()
