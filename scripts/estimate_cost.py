"""Dated gross planning model; run after reviewing current official price evidence.

This is a workload estimate, never an AWS spending cap. USD, Stockholm origins,
European CloudFront viewers, before credits and optional free allowances.
"""

import json
from decimal import Decimal as D
from pathlib import Path

DATE = "2026-11-18"
MONTH_SECONDS = D(30 * 86400)
RATES = {
    "lambda_request": D("0.0000002"),
    "lambda_gb_s": D("0.0000166667"),
    "api_request": D("0.00000106"),
    "event": D("0.000001"),
    "sqs_request": D("0.0000004"),
    "ddb_write": D("0.00000067"),
    "ddb_read": D("0.0000001345"),
    "ddb_gb": D("0.269"),
    "state_transition": D("0.000025"),
    "sns_request": D("0.0000005"),
    "email": D("0.00002"),
    "s3_put": D("0.000005"),
    "s3_get": D("0.0000004"),
    "s3_gb": D("0.023"),
    "log_ingest_gb": D("0.54"),
    "log_store_gb": D("0.028"),
    "alarm_month": D("0.10"),
    "trace": D("0.000005"),
    "trace_access": D("0.0000005"),
    "kms": D("0.000003"),
    "athena_tb": D("5"),
    "catalog_request": D("0.000001"),
    "catalog_object": D("0.00001"),
    "cf_gb": D("0.085"),
    "cf_https": D("0.0000012"),
    "direct_out_gb": D("0.09"),
}
SOURCES = {
    "regional_rates": "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json",
    "lambda": "https://aws.amazon.com/lambda/pricing/",
    "dynamodb": "https://aws.amazon.com/dynamodb/pricing/on-demand/",
    "step_functions": "https://aws.amazon.com/step-functions/pricing/",
    "cloudwatch": "https://aws.amazon.com/cloudwatch/pricing/",
    "athena": "https://aws.amazon.com/athena/pricing/",
    "cloudfront": "https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/",
    "s3": "https://aws.amazon.com/s3/pricing/",
    "sqs": "https://aws.amazon.com/sqs/pricing/",
    "sns": "https://aws.amazon.com/sns/pricing/",
    "api": "https://aws.amazon.com/api-gateway/pricing/",
    "eventbridge": "https://aws.amazon.com/eventbridge/pricing/",
    "kms": "https://aws.amazon.com/kms/pricing/",
    "glue": "https://aws.amazon.com/glue/pricing/",
    "xray": "https://aws.amazon.com/xray/pricing/",
}


def estimate(sessions, reports, months, transfer_gb, cf_requests, unit_kib=192):
    # 100 distinct readings/session, 10% retry allowance. Assume heavily populated
    # unit aggregates (192 KiB), not just the small clean-database smoke test.
    sessions, reports, months = D(sessions), D(reports), D(months)
    readings, retries = sessions * 100, D("1.10")
    invocations = (sessions * 650 + reports * 32) * retries
    log_gb = invocations * 2048 / D(1024**3)
    unit_read_ru = D(unit_kib) / 4
    # Ingestion + detector + five-unit offline checks on each tick + 60 UI polls.
    reads = sessions * (100 * unit_read_ru * 2 + 101 * (5 * unit_read_ru + 2) + 60 * (5 * unit_read_ru + 2) + 300)
    # UNIT transaction + READ dedup; only changed incidents are re-written.
    writes = readings * (2 * unit_kib + 2) + sessions * 1000 + reports * 200
    transition_count = sessions * (303 + 160) + reports * 96
    events = sessions * 120
    query_scan_tb = reports * D(10 * 1024 * 1024) / D(10**12)
    charges = {
        "lambda": invocations * (RATES["lambda_request"] + D("0.125") * 2 * RATES["lambda_gb_s"]),
        "http_api": (readings + sessions * 70 + reports * 2) * retries * RATES["api_request"],
        "eventbridge": events * retries * RATES["event"],
        # Two event-source mappings, conservative five empty long-pollers each.
        "sqs": (MONTH_SECONDS * months / 20 * 10 + events * 6 * retries) * RATES["sqs_request"],
        "dynamodb": writes * retries * RATES["ddb_write"]
        + reads * retries * RATES["ddb_read"]
        + D("0.01") * months * RATES["ddb_gb"],
        "step_functions": transition_count * retries * RATES["state_transition"],
        "sns_email": sessions * 4 * retries * (RATES["sns_request"] + RATES["email"]),
        "s3": (events + reports * 2 + 20 * months) * retries * RATES["s3_put"]
        + (D(cf_requests) + reports * 20) * RATES["s3_get"]
        + D("0.08") * months * RATES["s3_gb"],
        "logs": log_gb * RATES["log_ingest_gb"] + log_gb * D(7) / 30 * RATES["log_store_gb"],
        "alarms": 13 * months * RATES["alarm_month"],
        "custom_metrics": D(0),
        "traces": invocations * RATES["trace"] + sessions * 10 * RATES["trace_access"],
        "ssm_kms": sessions * 280 * retries * RATES["kms"],
        "athena": query_scan_tb * RATES["athena_tb"],
        "glue_catalog": reports * 20 * RATES["catalog_request"] + 2 * months * RATES["catalog_object"],
        "cloudfront": D(transfer_gb) * RATES["cf_gb"] + D(cf_requests) * RATES["cf_https"],
        "direct_api_transfer": sessions * D("0.003") * RATES["direct_out_gb"],
    }
    return {
        "sessions": str(sessions),
        "distinct_readings": str(readings),
        "reports": str(reports),
        "unit_state_kib": unit_kib,
        "assumed_retry_multiplier": str(retries),
        "estimated_gross_usd": str(sum(charges.values())),
        "charges_usd": {k: str(v) for k, v in charges.items()},
    }


def main():
    output = {
        "priced_at": DATE,
        "currency": "USD",
        "region": "eu-north-1",
        "sources": SOURCES,
        "assumptions": [
            "13 standard alarms; no custom metrics or CloudWatch dashboard",
            "128 MiB Lambda, two seconds per invocation",
            "100% trace sampling upper estimate",
            "Seven-day logs, 80 MB stored objects/versions, 10 MB DynamoDB",
            "Athena 10 MiB/query including minimum billing, max 20 queries/day",
            "10 sessions/day, max 100 distinct readings/session; no recurring producer",
            "SQS five empty long-pollers/queue, ten total; native DynamoDB-to-Lambda stream polling excluded",
            "Two European CDN GB and 20k HTTPS requests for 30 light sessions; higher traffic in restart scenario",
        ],
        "cases": {
            "one_demo_and_one_report_one_hour": estimate(1, 1, D(1) / 720, "0.07", 700),
            "idle_30_days": estimate(0, 0, 1, 0, 0),
            "light_30_days": estimate(30, 30, 1, 2, 20000),
            "accidental_restarts_at_daily_limits_30_days": estimate(300, 600, 1, 20, 200000),
        },
        "excluded_or_uncertain": [
            "Taxes, unrelated account usage, abuse or compromised credentials, retry storms beyond the allowance",
            "Unbounded physical-device/CLI traffic bypasses dashboard session limits",
            "Free allowances and detailed credit eligibility/expiry are not assumed",
            "Cost Explorer lookups and audit API activity: allow an additional $0.10–$0.50",
            "Query cancellation and scan limits are protective controls, not exact spending caps",
        ],
    }
    path = Path(".local/mvp-cost-model.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(output, indent=2))
    for name, case in output["cases"].items():
        print(name, "$" + str(D(case["estimated_gross_usd"]).quantize(D("0.01"))))


if __name__ == "__main__":
    main()
