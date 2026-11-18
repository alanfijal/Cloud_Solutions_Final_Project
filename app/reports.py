"""Fixed Athena reports with a global lease, daily quota and bounded workflow."""

import hashlib
import hmac
import json
import os
import time

from app.domain import ID
from app.fleet import Conflict
from app.handlers import log, response, secret
from app.store import Store, client

SLOT = "REPORT#active"
WINDOWS = {"1h": 3600, "24h": 86400, "7d": 604800}


def sql(units, start, end):
    # Identifiers come from the Terraform allowlist; times are server-created ints.
    if not units or any(not isinstance(u, str) or not ID.fullmatch(u) for u in units):
        raise ValueError("Invalid unit IDs")
    names = ", ".join("'" + u + "'" for u in units)
    database = os.environ["CATALOG_DATABASE"]
    if not database.replace("_", "").isalnum():
        raise ValueError("Invalid catalog database")
    return f"""
WITH deliveries AS (
 SELECT *, row_number() OVER (PARTITION BY unit_id, event_type, event_id ORDER BY "$path") AS delivery
 FROM {database}.events WHERE unit_id IN ({names})
), readings AS (
 SELECT unit_id, temperature, try(from_iso8601_timestamp(observed_at)) AS stamp,
 try_cast(json_extract_scalar(detail, '$.configuration.threshold') AS double) AS threshold,
 json_extract_scalar(detail, '$.configuration.direction') AS direction,
 coalesce(try_cast(json_extract_scalar(detail, '$.configuration.interval_s') AS integer), 30) AS interval_s
 FROM deliveries WHERE delivery = 1 AND event_type = 'reading.received'
), windowed AS (
 SELECT *, lead(stamp) OVER (PARTITION BY unit_id ORDER BY stamp) AS next_stamp
 FROM readings WHERE stamp >= from_unixtime({int(start)}) AND stamp <= from_unixtime({int(end)})
), spans AS (
 SELECT *, CASE WHEN threshold IS NOT NULL AND direction IN ('max', 'min')
 AND date_diff('second', stamp, next_stamp) BETWEEN 0 AND greatest(90, interval_s * 3)
 THEN date_diff('second', stamp, next_stamp) ELSE 0 END AS seconds,
 CASE WHEN direction = 'max' THEN temperature > threshold WHEN direction = 'min' THEN temperature < threshold ELSE false END AS outside
 FROM windowed
), temperatures AS (
 SELECT unit_id, count(*) AS readings, min(temperature) AS minimum, max(temperature) AS maximum,
 avg(temperature) AS average, sum(seconds) AS observed_seconds,
 sum(CASE WHEN outside THEN seconds ELSE 0 END) AS excursion_seconds,
 count_if(threshold IS NULL) AS unclassified_readings,
 min(to_iso8601(stamp)) AS first_reading, max(to_iso8601(stamp)) AS last_reading
 FROM spans GROUP BY unit_id
), incident_events AS (
 SELECT unit_id, incident_id,
 min(CASE WHEN event_type IN ('incident.opened', 'device.offline') THEN try_cast(json_extract_scalar(detail, '$.occurred_at') AS bigint) END) AS opened,
 min(CASE WHEN event_type = 'incident.acknowledged' THEN try_cast(json_extract_scalar(detail, '$.occurred_at') AS bigint) END) AS acknowledged,
 min(CASE WHEN event_type IN ('incident.resolved', 'device.online') THEN try_cast(json_extract_scalar(detail, '$.occurred_at') AS bigint) END) AS resolved
 FROM deliveries WHERE delivery = 1 AND incident_id IS NOT NULL
 AND try_cast(json_extract_scalar(detail, '$.occurred_at') AS bigint) BETWEEN {int(start)} AND {int(end)}
 GROUP BY unit_id, incident_id
), incidents AS (
 SELECT unit_id, count_if(opened IS NOT NULL) AS incidents,
 avg(CASE WHEN acknowledged >= opened THEN acknowledged - opened END) AS response_seconds,
 avg(CASE WHEN resolved >= opened THEN resolved - opened END) AS recovery_seconds
 FROM incident_events GROUP BY unit_id
), units AS (SELECT unit_id FROM temperatures UNION SELECT unit_id FROM incidents)
SELECT u.unit_id, coalesce(t.readings, 0) AS readings, t.minimum, t.maximum, t.average,
 coalesce(t.observed_seconds, 0) AS observed_seconds, coalesce(t.excursion_seconds, 0) AS excursion_seconds,
 coalesce(t.unclassified_readings, 0) AS unclassified_readings,
 coalesce(i.incidents, 0) AS incidents, i.response_seconds, i.recovery_seconds, t.first_reading, t.last_reading
FROM units u LEFT JOIN temperatures t ON u.unit_id = t.unit_id LEFT JOIN incidents i ON u.unit_id = i.unit_id
ORDER BY u.unit_id LIMIT 5
"""


def public(record):
    if not record:
        return None
    return {k: v for k, v in (record or {}).items() if k not in ("request_hash", "day", "daily_count", "query")}


def start(body, store=None, now=None):
    store, now = store or Store(), int(time.time()) if now is None else now
    if set(body) != {"request_id", "units", "window"}:
        raise ValueError("Choose devices and a report window")
    if not isinstance(body["request_id"], str) or not ID.fullmatch(body["request_id"]):
        raise ValueError("Invalid request ID")
    units = body["units"]
    if (
        not isinstance(units, list)
        or not 1 <= len(units) <= 5
        or len(set(units)) != len(units)
        or any(u not in json.loads(os.environ["UNITS"]) for u in units)
    ):
        raise ValueError("Select 1–5 configured devices")
    if body["window"] not in WINDOWS:
        raise ValueError("Report window must be 1h, 24h or 7d")
    units = sorted(units)
    digest = hashlib.sha256(json.dumps({"units": units, "window": body["window"]}, sort_keys=True).encode()).hexdigest()

    def claim(old):
        if old and old["request_id"] == body["request_id"]:
            if old["request_hash"] != digest:
                raise Conflict("The request ID belongs to different report settings")
            return old
        if old and old["status"] not in ("succeeded", "failed", "cancelled"):
            raise Conflict("A report is already running; wait for it to finish")
        if old and old["status"] == "succeeded" and old["request_hash"] == digest and now - old["created_at"] < 300:
            return old
        count = old.get("daily_count", 0) if old and old.get("day") == now // 86400 else 0
        if count >= 20:
            raise Conflict("The workspace has reached its 20-report daily demo limit")
        return {
            "request_id": body["request_id"],
            "request_hash": digest,
            "units": units,
            "window": body["window"],
            "start": now - WINDOWS[body["window"]],
            "end": now,
            "created_at": now,
            "deadline": now + 60,
            "status": "queued",
            "day": now // 86400,
            "daily_count": count + 1,
            "rows": [],
        }

    # Recover an abandoned start or timed-out worker before taking the slot.
    previous, _ = store.get(SLOT)
    if (
        previous
        and previous.get("deadline", now + 1) <= now
        and previous["status"] not in ("succeeded", "failed", "cancelled")
    ):
        if previous.get("query_id"):
            client("athena").stop_query_execution(QueryExecutionId=previous["query_id"])
        store.mutate(
            SLOT,
            lambda old: {**old, "status": "cancelled"} if old and old["request_id"] == previous["request_id"] else old,
        )
    record = store.mutate(SLOT, claim)
    if record["status"] == "succeeded":
        return public(record)
    try:
        client("stepfunctions").start_execution(
            stateMachineArn=os.environ["REPORT_WORKFLOW"],
            name=record["request_id"],
            input=json.dumps({"request_id": record["request_id"], "poll": 0}, sort_keys=True),
        )
    except client("stepfunctions").exceptions.ExecutionAlreadyExists:
        store.mutate(
            SLOT,
            lambda old: {**old, "status": "failed", "error": "Report ID was already used"}
            if old["request_id"] == record["request_id"]
            else old,
        )
        raise Conflict("This report ID was already used; request a new report") from None
    return public(record)


def advance(payload, context=None, store=None, now=None):
    store, now = store or Store(), int(time.time()) if now is None else now
    record, _ = store.get(SLOT)
    rid, poll = payload["request_id"], int(payload.get("poll", 0))
    done = {"request_id": rid, "poll": poll, "done": True}
    if not record or record["request_id"] != rid or record["status"] in ("succeeded", "failed", "cancelled"):
        return done
    athena = client("athena")
    if now >= record["deadline"] or poll >= 30 or payload.get("action") == "cancel":
        if record.get("query_id"):
            athena.stop_query_execution(QueryExecutionId=record["query_id"])
        store.mutate(
            SLOT,
            lambda old: {**old, "status": "cancelled", "error": "Report exceeded its bounded query window"}
            if old["request_id"] == rid
            else old,
        )
        return done
    if not record.get("query_id"):
        query_id = athena.start_query_execution(
            QueryString=sql(record["units"], record["start"], record["end"]),
            WorkGroup=os.environ["ATHENA_WORKGROUP"],
            ClientRequestToken=hashlib.sha256((rid + record["request_hash"] + str(record["end"])).encode()).hexdigest(),
        )["QueryExecutionId"]
        record = store.mutate(
            SLOT, lambda old: {**old, "query_id": query_id, "status": "running"} if old["request_id"] == rid else old
        )
    if record["request_id"] != rid:
        # The lease expired while Athena accepted the query. Cancel our orphan,
        # never read or overwrite the replacement job's result.
        athena.stop_query_execution(QueryExecutionId=query_id)
        return done
    result = athena.get_query_execution(QueryExecutionId=record["query_id"])["QueryExecution"]
    status = result["Status"]["State"]
    if status == "SUCCEEDED":
        data = athena.get_query_results(QueryExecutionId=record["query_id"], MaxResults=10)["ResultSet"]
        names = [c["Name"] for c in data["ResultSetMetadata"]["ColumnInfo"]]
        rows = [
            {key: cell.get("VarCharValue") for key, cell in zip(names, row["Data"], strict=True)}
            for row in data["Rows"][1:]
        ]

        def complete(old):
            return (
                {
                    **old,
                    "status": "succeeded",
                    "rows": rows,
                    "bytes_scanned": result.get("Statistics", {}).get("DataScannedInBytes", 0),
                    "completed_at": now,
                }
                if old["request_id"] == rid
                else old
            )

        store.mutate(SLOT, complete)
        log(
            "report_complete",
            request_id=rid,
            query_id=record["query_id"],
            bytes_scanned=result.get("Statistics", {}).get("DataScannedInBytes", 0),
        )
        return done
    if status in ("FAILED", "CANCELLED"):
        store.mutate(
            SLOT,
            lambda old: {
                **old,
                "status": "failed",
                "error": "Athena could not complete the bounded report; inspect the query in AWS",
            }
            if old["request_id"] == rid
            else old,
        )
        return done
    return {"request_id": rid, "poll": poll + 1, "done": False}


def handler(event, context):
    if "requestContext" not in event:
        return advance(event, context)
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    if not hmac.compare_digest(
        headers.get("authorization", "").encode(), ("Bearer " + secret(os.environ["DASHBOARD_PARAMETER"])).encode()
    ):
        return response(401, {"error": "Enter a valid operator access key"})
    method = event["requestContext"]["http"]["method"]
    try:
        if method == "GET":
            return response(200, public(Store().get(SLOT)[0]))
        if method == "POST":
            if len(event.get("body", "")) > 2048:
                raise ValueError("Report request is too large")
            return response(202, start(json.loads(event.get("body", ""))))
        return response(405, {"error": "Method not allowed"})
    except Conflict as exc:
        return response(409, {"error": str(exc)})
    except (ValueError, KeyError, TypeError):
        return response(400, {"error": "Invalid report request"})
