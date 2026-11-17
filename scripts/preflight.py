"""Read-only account and relevant-resource inventory; no settings are activated."""

import json
import pathlib
import subprocess

from aws_local import aws_json, identity


def main():
    report = {"identity": identity(), "checks": {}}
    checks = {
        "plan": ("freetier", "get-account-plan-state", [], "us-east-1"),
        "lambda_quota": ("lambda", "get-account-settings", [], "eu-north-1"),
        "functions": ("lambda", "list-functions", ["--query", "Functions[].FunctionName"], "eu-north-1"),
        "buckets": ("s3api", "list-buckets", ["--query", "Buckets[].Name"], "eu-north-1"),
        "queues": ("sqs", "list-queues", ["--queue-name-prefix", "coldchain-"], "eu-north-1"),
        "tables": ("dynamodb", "list-tables", [], "eu-north-1"),
        "buses": ("events", "list-event-buses", ["--name-prefix", "coldchain-"], "eu-north-1"),
        "workflows": ("stepfunctions", "list-state-machines", ["--query", "stateMachines[].name"], "eu-north-1"),
        "apis": ("apigatewayv2", "get-apis", ["--query", "Items[].{name:Name,id:ApiId}"], "eu-north-1"),
        "topics": ("sns", "list-topics", [], "eu-north-1"),
        "project_roles": (
            "iam",
            "list-roles",
            ["--query", "Roles[?starts_with(RoleName, `coldchain-`)].RoleName"],
            "eu-north-1",
        ),
        "budgets": (
            "budgets",
            "describe-budgets",
            ["--account-id", "028718095604", "--query", "Budgets[].BudgetName"],
            "us-east-1",
        ),
    }
    for name, (service, operation, args, region) in checks.items():
        try:
            report["checks"][name] = {
                "status": "verified",
                "result": aws_json(service, operation, *args, region=region),
            }
        except subprocess.CalledProcessError as exc:
            report["checks"][name] = {"status": "unverified", "reason": exc.stderr.strip()}
    path = pathlib.Path(".local/inventory.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    path.chmod(0o600)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
