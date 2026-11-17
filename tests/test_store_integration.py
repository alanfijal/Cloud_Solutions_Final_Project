"""Test Store against an atomic in-memory DynamoDB contract, without AWS calls."""

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from app.domain import apply_reading, transition
from app.store import Store
from tests.test_domain import CFG, reading


class Canceled(ClientError):
    pass


class Database:
    exceptions = SimpleNamespace(TransactionCanceledException=Canceled)

    def __init__(self):
        self.items = {}
        self.lock = threading.RLock()

    def get_item(self, TableName, Key, ConsistentRead):
        assert ConsistentRead
        with self.lock:
            item = self.items.get(Key["pk"]["S"])
            return {"Item": copy.deepcopy(item)} if item else {}

    def transact_write_items(self, TransactItems):
        with self.lock:
            for write in TransactItems:
                put = write["Put"]
                key = put["Item"]["pk"]["S"]
                old = self.items.get(key)
                condition = put.get("ConditionExpression")
                if (condition == "attribute_not_exists(pk)" and old is not None) or (
                    condition == "#v = :v" and (not old or old["version"] != put["ExpressionAttributeValues"][":v"])
                ):
                    raise Canceled(
                        {
                            "Error": {"Code": "TransactionCanceledException"},
                            "CancellationReasons": [{"Code": "ConditionalCheckFailed"}],
                        },
                        "TransactWriteItems",
                    )
            for write in TransactItems:
                put = write["Put"]
                self.items[put["Item"]["pk"]["S"]] = copy.deepcopy(put["Item"])


def process(store, n):
    def change(old):
        state, events = apply_reading(old, reading(n), CFG, 100 + n * 30)
        return state, events, "processed"

    return store.update("unit-1", change, f"r{n}")


def test_duplicate_after_committed_http_or_sqs_retry():
    db = Database()
    store = Store(db, "test")
    assert process(store, 0) == "processed"
    before = copy.deepcopy(db.items)
    assert process(store, 0) == "duplicate"
    assert db.items == before


def test_concurrent_duplicate_third_reading_opens_once_and_outbox_survives():
    db = Database()
    store = Store(db, "test")
    process(store, 0)
    process(store, 1)
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: process(store, 2), range(8)))
    assert results.count("processed") == 1
    assert results.count("duplicate") == 7
    assert sum(k.startswith("OUT#") for k in db.items) == 1
    assert sum(k.startswith("INCIDENT#") for k in db.items) == 1
    assert store.get("UNIT#unit-1")[0]["count"] == 3
    # No publisher ran: the event is still durably present for stream retry/replay.
    assert (
        json.loads(next(v["payload"]["S"] for k, v in db.items.items() if k.startswith("OUT#")))["type"]
        == "incident.opened"
    )


def test_real_store_cas_ack_races_with_escalation():
    db = Database()
    store = Store(db, "test")
    for n in range(3):
        process(store, n)
    iid = store.get("UNIT#unit-1")[0]["incident"]["incident_id"]
    with ThreadPoolExecutor(2) as pool:
        list(
            pool.map(
                lambda action: store.update("unit-1", lambda old: transition(old, iid, action, 300)), ["ack", "check"]
            )
        )
    incident = store.get("UNIT#unit-1")[0]["incident"]
    assert incident["acknowledged"]
    assert store.get("INCIDENT#" + iid)[0] == incident
    assert store.update("unit-1", lambda old: transition(old, iid, "check", 301)) == "acknowledged"


def test_atomic_conflict_writes_nothing():
    db = Database()
    store = Store(db, "test")
    process(store, 0)
    before = copy.deepcopy(db.items)
    writes = [
        {"Put": {"TableName": "test", "Item": {"pk": {"S": "OUT#must-not-exist"}}}},
        {
            "Put": {
                "TableName": "test",
                "Item": db.items["READ#unit-1#r0"],
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
    ]
    with pytest.raises(Canceled):
        db.transact_write_items(TransactItems=writes)
    assert db.items == before
