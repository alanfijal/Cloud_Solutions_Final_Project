# Cold-Chain Monitor

Small AWS temperature-monitoring demo for the ESADE Cloud Solutions project.
**Dev is deployed in Stockholm. The bounded AWS rehearsal and GitHub checks passed.**

The web dashboard uses **private S3 + CloudFront**, with authenticated API access
for temperatures, recent charts, incidents, acknowledgement and demo controls.
Open `dashboard_url` from Terraform outputs and connect with the operator key:

```bash
pbcopy < .local/dashboard-credential-dev.txt
# Open dashboard_url in your browser, paste the key, and choose Open workspace.
```

Choose **Start guided demo**, or use **Send your own reading** to try individual
temperatures. The guided demo sends one reading every six seconds across five
units (each unit every 30 seconds), stopping at 100 readings or ten minutes.
**Stop simulation**, disconnecting, or closing the tab stops future submissions.
Don't run the CLI simulator at the same time. Auto-refresh stops after ten minutes;
Refresh resumes it. Charts show the latest 20 accepted readings per unit; full
history remains in S3/Athena. The shared demo operator key stays in tab memory;
device keys and signed acknowledgement credentials stay server-side. Multi-user
accounts and role management are outside this demonstration's scope.

```text
Browser → CloudFront → private S3 dashboard files
                    → HTTP API → authenticated dashboard Lambda
Simulator → HTTP API → ingest Lambda → EventBridge → SQS → detector → DynamoDB
                                             ↑                   ↓ outbox stream
                                   publisher Lambda ←────────────┘
EventBridge → dispatcher → Step Functions → staff email → wait/check → manager email
EventBridge → lake SQS → batched S3 history → Glue catalog → Athena
Email link → GET confirmation → POST acknowledgement → DynamoDB
```

Three newer out-of-range readings open one incident; normal readings reset the
counter and resolve it. Older/equal-time readings are ignored, and gaps over
90 seconds reset the count. This is consecutive **accepted** readings, not a
reconstruction of unordered sensor history. Demo maxima: fridge 5°C, freezer
-18°C; these are project settings, not regulatory guidance.

Updates, incident snapshots, deduplication and outbox events commit atomically.
Delivery/email remain at least once. The bounded Standard workflow checks every
30 seconds, escalates after 120 seconds and supports late acknowledgement.
Links expire after one hour; GET cannot acknowledge. Recovery suppresses pending
escalation, but an already in-flight email cannot be recalled. S3 versioning is
recovery support, not legal immutability. SQL deduplicates overlapping batches.

## Local checks

Requires Python 3.13 and Terraform **1.17.0**. AWS access is unnecessary for tests.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/ruff check app simulator scripts tests
.venv/bin/pytest -q
.venv/bin/python scripts/package.py
.venv/bin/python -m scripts.demo_local
terraform fmt -check -recursive infra
# Optional local browser checks; CI also runs these with a mocked API:
.venv/bin/python -m pip install --require-hashes -r requirements-browser.lock
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/check_dashboard_browser.py
```

Initialize each Terraform root with `init -backend=false -lockfile=readonly`.
Run `terraform test` in `infra/bootstrap` and `infra/modules/platform`; both use
mocked providers and create no AWS resources. Local evidence: **57 Python tests**,
two Terraform tests, all four root validations, actionlint, runtime dependency
audit and Trivy's HIGH/CRITICAL gate passed. Three narrow cost/security scan exceptions
are recorded in `.trivyignore.yaml`. Independent package builds matched, including
in a fresh hash-locked environment. [GitHub CI](https://github.com/alanfijal/Cloud_Solutions_Final_Project/actions/runs/44142650120)
and [delivery preparation](https://github.com/alanfijal/Cloud_Solutions_Final_Project/actions/runs/44142940523)
passed; the Linux-built artifact matches all seven live Lambda code hashes.

AWS rehearsal, 17 November 2026: 100 distinct readings plus one duplicate replay;
normal/spike/reset, sustained breach, escalation, late POST acknowledgement and
recovery passed. Invalid input/authentication and expired acknowledgement were
rejected; GET did not acknowledge. The owner confirmed both staff and manager
emails arrived. Athena returned all 100 readings and five lifecycle events,
scanning 53,684 bytes. The local monitor's exported credentials expired after 80
readings; refreshing from the existing CLI profile completed the remaining 20
without restarting the workload. Failure paths and concurrency were tested
locally; Terraform tests checked DLQ/redrive and workflow timeout configuration.
No AWS fault injection or forced redrive was performed.

Terraform is split by service: `lambda.tf`, `iam.tf`, `queues.tf`, `api.tf`,
`eventbridge.tf`, `dynamodb.tf`, `s3.tf`, `sns.tf`, `step_functions.tf`,
`glue.tf`, `athena.tf`, and `cloudwatch.tf`. Environment `main.tf` files only
wire the reusable module; providers, variables, backend and outputs are separate.

| Course area | Coverage |
|---|---|
| IaC and cloud services | Implemented: reusable Terraform, private S3 state, native locking, serverless services and S3/CloudFront web hosting |
| Git-managed delivery | Implemented: pinned GitHub checks/artifacts and reviewed local saved-plan apply; OIDC blocked by account policy |
| Event processing | Implemented: buffering, transactional outbox, deduplication and bounded escalation |
| Analytics and observability | Implemented: S3/Glue/Athena SQL, JSON logs, nine alarms and sampled native traces |
| Richer processing, ML and GenAI | Future work: Parquet/ETL, silence detection, trained models and GenAI; no optional services deployed |

SQS batches replace Firehose for this small workload; Firehose also requires a
Paid plan on this signup. A known Glue schema avoids a crawler. Lambda validates
HTTP API JSON; a bounded Wait/Choice workflow replaces emailed callback tokens.
These choices retain the event-driven course coverage with fewer moving parts.

## Account and cost controls

Account **028718095604**, region **eu-north-1**. The existing temporary browser
profile is `coldchain-console`; override with `COLDCHAIN_PROFILE`. Helpers verify
STS, reject root/account mismatches, and pass temporary credentials in memory.
No static keys or secret values enter Git/Terraform. See [AWS browser login](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html).

Verified 17 November 2026: ACTIVE Free plan, **$160 remaining** after deployment
($100 before deployment), plan expiry 17 May 2027. The reason for the balance
increase is unverified; the spending target remains unchanged. The last gross
usage result was $0 **estimated**, before delayed deployment/demo charges.
Detailed credit eligibility/expiry remains unverified because billing access is
restricted. The owner approved GitHub CI plus **reviewed local delivery**: this
signup's policy blocks OIDC providers. No paid upgrade is authorized.

Stockholm public prices checked 17 November 2026, before credits/free allowances:

| Scenario | Estimated gross USD |
|---|---:|
| One 100-reading demo, one hour deployed | 0.11 |
| 30 days, one demo per day | 2.01 |
| Accidental continuous repeated demos for 30 days | 29.57 |

Model: 20% retry allowance, 128 MiB/250 ms average Lambda calls, transactional
writes, idle SQS polling, workflow transitions, S3, KMS, logs, nine alarms,
conservative tracing and bounded query/transfer allowances. Tax, unrelated usage,
attacks and retry storms are excluded. Eligible charges should consume credits;
zero cash is expected while the Free plan stays active, not because a card is
absent. Keep the **$25 total target and $50 reserve**. These are not hard caps.
[Stockholm API tariffs](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonApiGateway/current/eu-north-1/index.json),
[Lambda tariffs](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSLambda/current/eu-north-1/index.json),
[CloudWatch tariffs](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonCloudWatch/current/eu-north-1/index.json)
and the other service rate snapshots/calculation are retained privately in `.local/`.
[Free plan restrictions](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html).

Dashboard addition priced 17 November 2026: 10 MB of static files, 1 GB/month
served in Europe, 10,000 HTTPS requests and 100 uploads give approximately
**$0.10/month** of S3/CloudFront hosting before credits/free allowances. Thirty
bounded demo/dashboard sessions add about **$0.19/month**, including UI API calls,
key access, traces/logs and larger bounded history writes. Reserve **$0.50/month**
for the addition, giving approximately **$2.51/month** with the existing light-use
baseline. This is a planning allowance, not a cap. The same hosting workload on
Amplify with 30 standard build minutes is approximately $0.45/month.
[CloudFront pay-as-you-go](https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/),
[S3 pricing](https://aws.amazon.com/s3/pricing/),
[Amplify pricing](https://aws.amazon.com/amplify/pricing/).
No CloudFront flat-rate plan, account upgrade, custom domain, WAF subscription or
edge function is enabled. CloudFront is global; private buckets/functions remain
in Stockholm. OAC signs S3 origin requests; authenticated API responses use
CachingDisabled with Authorization forwarded. Static assets can cache for 60 seconds.

Deployed after owner approval: **7 bootstrap + 100 application/configuration resources**,
six runtime SecureString parameters, and state/recovery objects; one dev environment.
Budget warnings at actual $5/$10/$20/$25 and forecast $25 cover 17 Nov–17 Dec 2026,
exclude credits/refunds and require email verification where AWS requests it.
All five notifications were verified. They are delayed warnings. Budgets uses the
us-east-1 endpoint; IAM is global. Plans and detailed evidence stay private in `.local/`.

## Deploy after approval

Ignored `local.tfvars.json` files are already configured for the owner. For a fresh
checkout, bootstrap needs `{"budget_email":"you@example.com"}`; dev needs
`{"alert_email":"you@example.com"}` in their respective directories. Copy
`backend.example.hcl` to `backend.hcl` and set the approved state bucket.

```bash
.venv/bin/python scripts/preflight.py
.venv/bin/python scripts/terraform_local.py bootstrap init
.venv/bin/python scripts/terraform_local.py bootstrap plan
# Review the exact saved plan; apply only after owner approval:
.venv/bin/python scripts/terraform_local.py bootstrap apply --confirm-account 028718095604
aws s3 cp infra/bootstrap/terraform.tfstate \
  s3://coldchain-028718095604-tfstate/recovery/bootstrap.tfstate \
  --sse AES256 --profile coldchain-console --region eu-north-1
.venv/bin/python scripts/terraform_local.py dev init
.venv/bin/python scripts/terraform_local.py dev plan
.venv/bin/python scripts/terraform_local.py dev apply --confirm-account 028718095604
.venv/bin/python scripts/provision_devices.py --environment dev --confirm-account 028718095604
.venv/bin/python scripts/terraform_local.py dev output
```

`show` displays a saved plan. Apply checks clean committed source, package/plan
hashes, age, account and explicit confirmation. A pre-bootstrap `dev preview` is
isolated and **cannot be applied**. After bootstrap, review the real backend plan
against the approved preview. Both environments share one locked state key;
never deploy both. Retain bootstrap state locally on encrypted storage and in its
private recovery backup. Ordinary application destroy preserves that backend.

## Demo and cleanup

All three SNS subscriptions are confirmed for the current deployment. On a fresh
deployment, confirm them before running the simulator. Run it with the returned
API URL and `.local/device-credentials-dev.json`; it sends at most 100 readings,
three HTTP attempts each, for at most ten minutes on macOS/Linux. Ctrl-C stops it.
Normal → single spike/reset → sustained breach (~150 s) → staff → escalation
(~270 s) → explicit POST acknowledgement → recovery (~450 s), plus queue latency.

```bash
.venv/bin/python -m simulator.run --url https://REPLACE.execute-api.eu-north-1.amazonaws.com \
  --credentials .local/device-credentials-dev.json
.venv/bin/python scripts/query_history.py --environment dev
```

Runnable queries are in `analytics/sql/`. Show JSON logs, queue age/DLQs, native
alarms and sampled traces; asynchronous hops are correlated by domain IDs, not an
automatically complete trace. If email is missing, check subscription confirmation
and dispatch/async DLQs. Inspect failures before replaying; do not auto-redrive all.

No recurring producer, crawler or query exists. A reviewed pause sets
`ingestion_enabled=false` and `consumers_enabled=false`, retaining state. Logs
retain seven days, raw data fourteen days, query results seven days. Native/managed
encryption avoids CMK monthly fees; the operations topic has no SNS SSE so native
alarm delivery works without a CMK. Optional ETL/Parquet, silence detection,
statistical trends, CloudWatch dashboards, trained ML and GenAI are not deployed.

Cleanup requires explicit data-loss approval: stop/drain writers, run
`empty_demo_buckets.py --environment dev --confirm-account 028718095604 --confirm-data-loss`,
review `terraform_local.py dev destroy-plan`, then apply it with both confirmation
flags. Run `cleanup_parameters.py` with the same environment/account/data-loss
flags. Only tagged application data/resources are targeted. Backend removal
requires separate approval and state export; retained state versions still have
small storage charges. No cleanup has been executed.
