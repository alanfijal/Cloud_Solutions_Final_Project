"""Share AWS CLI browser-login temporary credentials without writing key material."""

import json
import os
import subprocess

import boto3
from botocore.config import Config

ACCOUNT = "028718095604"
REGION = "eu-north-1"
PROFILE = os.environ.get("COLDCHAIN_PROFILE", "coldchain-console")
CONFIG = Config(connect_timeout=3, read_timeout=10, retries={"mode": "standard", "total_max_attempts": 2})


def aws_json(service, operation, *args, region=REGION):
    result = subprocess.run(
        [
            "aws",
            service,
            operation,
            "--profile",
            PROFILE,
            "--region",
            region,
            "--output",
            "json",
            "--no-cli-pager",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def identity():
    result = aws_json("sts", "get-caller-identity")
    if result["Account"] != ACCOUNT:
        raise RuntimeError("Account mismatch: no further AWS operations are permitted")
    if result["Arn"].endswith(":root"):
        raise RuntimeError("Use an authorized non-root session")
    return {"account": result["Account"], "arn": result["Arn"], "region": REGION}


def temporary_credentials():
    identity()
    result = subprocess.run(
        ["aws", "configure", "export-credentials", "--profile", PROFILE, "--format", "process"],
        capture_output=True,
        text=True,
        check=True,
    )
    credentials = json.loads(result.stdout)
    if not credentials.get("SessionToken"):
        raise RuntimeError("Temporary session credentials are required")
    return credentials


def session():
    c = temporary_credentials()
    return boto3.Session(
        aws_access_key_id=c["AccessKeyId"],
        aws_secret_access_key=c["SecretAccessKey"],
        aws_session_token=c["SessionToken"],
        region_name=REGION,
    )


def terraform_env():
    c = temporary_credentials()
    env = os.environ.copy()
    for key in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_ROLE_ARN", "AWS_WEB_IDENTITY_TOKEN_FILE"):
        env.pop(key, None)
    env.update(
        AWS_ACCESS_KEY_ID=c["AccessKeyId"],
        AWS_SECRET_ACCESS_KEY=c["SecretAccessKey"],
        AWS_SESSION_TOKEN=c["SessionToken"],
        AWS_REGION=REGION,
        AWS_DEFAULT_REGION=REGION,
        TF_IN_AUTOMATION="1",
    )
    return env
