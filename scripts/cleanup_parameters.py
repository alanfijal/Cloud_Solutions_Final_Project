"""Explicitly approved application-secret cleanup, separate from protected backend."""

import argparse

from aws_local import ACCOUNT, CONFIG, session


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--environment", choices=["dev", "demo"], required=True)
    p.add_argument("--confirm-account", required=True)
    p.add_argument("--confirm-data-loss", action="store_true")
    args = p.parse_args()
    if args.confirm_account != ACCOUNT or not args.confirm_data_loss:
        p.error("Correct account and explicit --confirm-data-loss required after cleanup approval")
    names = [f"/coldchain-{args.environment}/devices/unit-{i}" for i in range(1, 6)]
    names.append(f"/coldchain-{args.environment}/ack")
    ssm = session().client("ssm", config=CONFIG)
    confirmed = []
    for name in names:
        exists = ssm.describe_parameters(ParameterFilters=[{"Key": "Name", "Option": "Equals", "Values": [name]}])[
            "Parameters"
        ]
        if not exists:
            continue
        tags = {
            t["Key"]: t["Value"]
            for t in ssm.list_tags_for_resource(ResourceType="Parameter", ResourceId=name)["TagList"]
        }
        if tags.get("Project") != "ColdChainMonitor" or tags.get("Environment") != args.environment:
            raise RuntimeError("Parameter ownership tags mismatch: refusing cleanup")
        confirmed.append(name)
    if confirmed:
        result = ssm.delete_parameters(Names=confirmed)
        if result.get("InvalidParameters"):
            raise RuntimeError("Some parameters were not removed; inspect before retrying")
    print("Removed", len(confirmed), "tagged project parameters; backend untouched.")


if __name__ == "__main__":
    main()
