"""Optimistic DynamoDB aggregate and transactional outbox."""

import json
import os
import random
import time
from functools import lru_cache

import boto3
from botocore.config import Config

CONFIG = Config(retries={"mode": "standard", "total_max_attempts": 3}, connect_timeout=3, read_timeout=5)


@lru_cache(maxsize=8)
def client(service):
    return boto3.client(service, config=CONFIG)


class Store:
    def __init__(self, dynamodb=None, table=None):
        self.db = dynamodb or client("dynamodb")
        self.table = table or os.environ["TABLE"]

    def get(self, key):
        item = self.db.get_item(TableName=self.table, Key={"pk": {"S": key}}, ConsistentRead=True).get("Item")
        return (json.loads(item["payload"]["S"]), int(item["version"]["N"])) if item else (None, 0)

    def update(self, unit, change, reading_id=None):
        for attempt in range(5):
            old, version = self.get("UNIT#" + unit)
            if reading_id and self.get(f"READ#{unit}#{reading_id}")[0] is not None:
                return "duplicate"
            state, events, result = change(old)
            writes = [
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": {
                            "pk": {"S": "UNIT#" + unit},
                            "payload": {"S": json.dumps(state)},
                            "version": {"N": str(version + 1)},
                        },
                        "ConditionExpression": "attribute_not_exists(pk)" if version == 0 else "#v = :v",
                        **(
                            {}
                            if version == 0
                            else {
                                "ExpressionAttributeNames": {"#v": "version"},
                                "ExpressionAttributeValues": {":v": {"N": str(version)}},
                            }
                        ),
                    }
                }
            ]
            if reading_id:
                writes.append(
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                "pk": {"S": f"READ#{unit}#{reading_id}"},
                                "payload": {"S": "{}"},
                                "version": {"N": "1"},
                                "ttl": {"N": str(int(time.time()) + 2592000)},
                            },
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    }
                )
            if state.get("incident"):
                incident = state["incident"]
                writes.append(
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                "pk": {"S": "INCIDENT#" + incident["incident_id"]},
                                "payload": {"S": json.dumps(incident)},
                                "version": {"N": str(version + 1)},
                                "ttl": {"N": str(int(time.time()) + 2592000)},
                            },
                        }
                    }
                )
            for e in events:
                writes.append(
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                "pk": {"S": "OUT#" + e["event_id"]},
                                "payload": {"S": json.dumps(e)},
                                "version": {"N": "1"},
                                "ttl": {"N": str(int(time.time()) + 2592000)},
                            },
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    }
                )
            try:
                self.db.transact_write_items(TransactItems=writes)
                return result
            except self.db.exceptions.TransactionCanceledException as exc:
                reasons = exc.response.get("CancellationReasons", [])
                if any(r.get("Code") not in ("None", "ConditionalCheckFailed", "TransactionConflict") for r in reasons):
                    raise
                time.sleep(random.uniform(0, 0.02 * 2**attempt))
        raise RuntimeError("optimistic update exhausted; retry message")
