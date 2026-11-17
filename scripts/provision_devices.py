"""Approved post-deployment step: provision runtime secrets outside Terraform state."""

import argparse
import json
import os
import secrets
from pathlib import Path

from aws_local import ACCOUNT, CONFIG, session


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--environment", choices=["dev", "demo"], default="dev")
    p.add_argument("--confirm-account", required=True)
    args = p.parse_args()
    if args.confirm_account != ACCOUNT:
        p.error("Expected account " + ACCOUNT)
    os.umask(0o077)
    ssm = session().client("ssm", config=CONFIG)
    prefix = "/coldchain-" + args.environment
    credentials = {}
    for suffix in [*(f"devices/unit-{i}" for i in range(1, 6)), "ack", "dashboard"]:
        name = prefix + "/" + suffix
        try:
            value = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
            tags = {
                t["Key"]: t["Value"]
                for t in ssm.list_tags_for_resource(ResourceType="Parameter", ResourceId=name)["TagList"]
            }
            if tags.get("Project") != "ColdChainMonitor" or tags.get("Environment") != args.environment:
                raise RuntimeError("Existing parameter ownership tags mismatch; refusing adoption")
        except ssm.exceptions.ParameterNotFound:
            value = secrets.token_urlsafe(32)
            ssm.put_parameter(
                Name=name,
                Value=value,
                Type="SecureString",
                Tier="Standard",
                Overwrite=False,
                Tags=[
                    {"Key": "Project", "Value": "ColdChainMonitor"},
                    {"Key": "Environment", "Value": args.environment},
                    {"Key": "Owner", "Value": "esade-project"},
                ],
            )
        if suffix.startswith("devices/"):
            credentials[suffix.split("/")[-1]] = value
        if suffix == "dashboard":
            dashboard_path = Path(".local/dashboard-credential-" + args.environment + ".txt")
            dashboard_path.parent.mkdir(exist_ok=True)
            dashboard_path.write_text(value)
            dashboard_path.chmod(0o600)
    path = Path(".local/device-credentials-" + args.environment + ".json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(credentials))
    path.chmod(0o600)
    print("Provisioned/reused seven standard SecureString parameters; local simulator credential file:", path)
    print("Operator access key saved privately:", dashboard_path)
    print("No credential values were logged. Existing parameters were not rotated.")


if __name__ == "__main__":
    main()
