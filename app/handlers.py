import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qs, urlencode

from app.domain import apply_reading, credential, transition, validate, verify_credential
from app.store import Store, client


def log(kind, **fields):
    print(json.dumps({"kind": kind, **fields}))


def secret(name):
    return client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]


def response(code, body, content_type="application/json"):
    return {
        "statusCode": code,
        "headers": {
            "content-type": content_type,
            "cache-control": "no-store",
            "referrer-policy": "no-referrer",
            "content-security-policy": "default-src 'none'; form-action 'self'; frame-ancestors 'none'",
        },
        "body": body if isinstance(body, str) else json.dumps(body),
    }


def publish(event):
    result = client("events").put_events(
        Entries=[
            {
                "EventBusName": os.environ["BUS"],
                "Source": "coldchain",
                "DetailType": event["type"],
                "Detail": json.dumps(event),
            }
        ]
    )
    if result.get("FailedEntryCount") or any("ErrorCode" in e for e in result["Entries"]):
        raise RuntimeError("EventBridge publication failed")


def ingest(event, context):
    if os.environ.get("INGESTION_ENABLED", "true") != "true":
        return response(503, {"error": "ingestion paused"})
    try:
        body = event.get("body", "")
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode()
        if len(body) > 4096:
            return response(413, {"error": "payload too large"})
        reading = validate(json.loads(body), time.time())
        config = json.loads(os.environ["UNITS"]).get(reading["unit_id"])
        if not config or config["site_id"] != reading["site_id"]:
            return response(401, {"error": "unauthorized"})
        supplied = {k.lower(): v for k, v in event.get("headers", {}).items()}.get("authorization", "")
        if not hmac.compare_digest(supplied, "Bearer " + secret(config["credential_parameter"])):
            return response(401, {"error": "unauthorized"})
        publish({"type": "reading.received", "event_id": reading["reading_id"], **reading})
        log("accepted", reading_id=reading["reading_id"], unit_id=reading["unit_id"])
        return response(202, {"reading_id": reading["reading_id"]})
    except (ValueError, TypeError, KeyError):
        return response(400, {"error": "invalid reading"})


def batch(event, process):
    failed = []
    for record in event["Records"]:
        try:
            process(record)
        except Exception as exc:
            log("batch_failure", message_id=record["messageId"], error_type=type(exc).__name__)
            failed.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failed}


def detector(event, context):
    store = Store()
    configs = json.loads(os.environ["UNITS"])

    def process(record):
        raw = json.loads(record["body"])["detail"]
        reading = validate(
            {k: raw[k] for k in ("reading_id", "unit_id", "site_id", "observed_at", "temperature", "schema_version")}
        )

        def change(old):
            state, events = apply_reading(old, reading, configs[reading["unit_id"]], int(time.time()))
            return state, events, "processed"

        result = store.update(reading["unit_id"], change, reading["reading_id"])
        log("detected", reading_id=reading["reading_id"], unit_id=reading["unit_id"], result=result)

    return batch(event, process)


def workflow(event, context):
    if event.get("source") == "aws.states":
        payload = json.loads(event["detail"]["input"])
        event = {**payload, "action": "failure"}

    def change(old):
        return transition(old or {}, event["incident_id"], event["action"], int(time.time()))

    status = Store().update(event["unit_id"], change)
    return {**event, "status": status}


def ack(event, context):
    try:
        method = event["requestContext"]["http"]["method"]
        params = event.get("queryStringParameters") or {}
        if method == "POST":
            body = event.get("body", "")
            if event.get("isBase64Encoded"):
                body = base64.b64decode(body).decode()
            params = {k: v[0] for k, v in parse_qs(body).items()}
        unit, iid, expiry, sig = (params[k] for k in ("unit", "incident", "expiry", "signature"))
        verify_credential(secret(os.environ["ACK_PARAMETER"]), unit, iid, expiry, sig, time.time())
        if method == "GET":
            # Validated values contain only identifiers, digits and hex; never reflect untrusted strings.
            return response(
                200,
                "<!doctype html><title>Confirm acknowledgement</title>"
                '<form method="post"><button type="submit">Acknowledge incident</button>'
                + "".join(
                    f'<input type="hidden" name="{k}" value="{v}">'
                    for k, v in {
                        "unit": unit,
                        "incident": iid,
                        "expiry": int(expiry),
                        "signature": credential(secret(os.environ["ACK_PARAMETER"]), unit, iid, int(expiry)),
                    }.items()
                )
                + "</form>",
                "text/html; charset=utf-8",
            )
        if method != "POST":
            return response(405, {"error": "method not allowed"})
        result = Store().update(unit, lambda old: transition(old or {}, iid, "ack", int(time.time())))
        return response(200, {"status": result})
    except (KeyError, ValueError, TypeError):
        return response(403, {"error": "invalid or expired acknowledgement"})


def outbox(event, context):
    # Raising retries the batch. Re-publication is at least once; stable IDs identify duplicates.
    for record in event["Records"]:
        if record["eventName"] != "INSERT":
            continue
        item = record["dynamodb"]["NewImage"]
        if not item["pk"]["S"].startswith("OUT#"):
            continue
        e = json.loads(item["payload"]["S"])
        publish(e)
        log("outbox_published", event_id=e["event_id"], incident_id=e["incident_id"])


def dispatch(event, context):
    """EventBridge invokes asynchronously; failures have a separate Lambda destination."""
    e = event["detail"]
    if e["type"] == "incident.opened":
        payload = json.dumps({"unit_id": e["unit_id"], "incident_id": e["incident_id"]}, sort_keys=True)
        try:
            client("stepfunctions").start_execution(
                stateMachineArn=os.environ["WORKFLOW"], name=e["incident_id"], input=payload
            )
        except client("stepfunctions").exceptions.ExecutionAlreadyExists:
            pass
    if e["type"] in ("notification.staff", "incident.escalated"):
        state, _ = Store().get("UNIT#" + e["unit_id"])
        incident = state["incident"]
        if incident["incident_id"] != e["incident_id"] or incident["status"] == "resolved" or incident["acknowledged"]:
            return
        expiry = incident["expires_at"]
        signature = credential(secret(os.environ["ACK_PARAMETER"]), e["unit_id"], e["incident_id"], expiry)
        link = (
            os.environ["API_URL"]
            + "/ack?"
            + urlencode({"unit": e["unit_id"], "incident": e["incident_id"], "expiry": expiry, "signature": signature})
        )
        audience = "STAFF_TOPIC" if e["type"] == "notification.staff" else "MANAGER_TOPIC"
        client("sns").publish(
            TopicArn=os.environ[audience],
            Subject="Cold-chain STAFF incident" if audience == "STAFF_TOPIC" else "Cold-chain MANAGER escalation",
            Message=f"Incident {e['incident_id']} for {e['unit_id']}. Confirm: {link}",
        )
    log("dispatched", event_id=e["event_id"], incident_id=e["incident_id"])


def lake(event, context):
    rows, accepted, failed = [], [], []
    for record in event["Records"]:
        try:
            e = json.loads(record["body"])["detail"]
            row = {
                "event_id": e["event_id"],
                "event_type": e["type"],
                "unit_id": e.get("unit_id"),
                "reading_id": e.get("reading_id"),
                "incident_id": e.get("incident_id"),
                "observed_at": e.get("observed_at"),
                "temperature": e.get("temperature"),
                "detail": json.dumps(e, sort_keys=True, separators=(",", ":")),
            }
            rows.append(json.dumps(row, sort_keys=True, separators=(",", ":")))
            accepted.append(record["messageId"])
        except (ValueError, KeyError, TypeError):
            failed.append({"itemIdentifier": record["messageId"]})
    if rows:
        body = ("\n".join(sorted(set(rows))) + "\n").encode()
        key = hashlib.sha256(body).hexdigest()
        try:
            client("s3").put_object(
                Bucket=os.environ["LAKE"],
                Key=f"raw/{key}.json",
                Body=body,
                ContentType="application/x-ndjson",
                IfNoneMatch="*",
            )
        except client("s3").exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] != "PreconditionFailed":
                log("lake_write_failure", error_type=type(exc).__name__)
                failed.extend({"itemIdentifier": mid} for mid in accepted)
        except Exception as exc:
            log("lake_write_failure", error_type=type(exc).__name__)
            failed.extend({"itemIdentifier": mid} for mid in accepted)
    return {"batchItemFailures": failed}
