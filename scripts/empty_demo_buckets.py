"""Approved data cleanup: only tagged application buckets, never the state backend."""

import argparse

from aws_local import ACCOUNT, CONFIG, session


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--environment", choices=["dev", "demo"], required=True)
    p.add_argument("--confirm-account", required=True)
    p.add_argument("--confirm-data-loss", action="store_true")
    args = p.parse_args()
    if args.confirm_account != ACCOUNT or not args.confirm_data_loss:
        p.error("Expected account and explicit --confirm-data-loss required after cleanup approval")
    s3 = session().client("s3", config=CONFIG)
    for zone in ("lake", "queries"):
        bucket = f"coldchain-{args.environment}-{ACCOUNT}-{zone}"
        tags = {t["Key"]: t["Value"] for t in s3.get_bucket_tagging(Bucket=bucket)["TagSet"]}
        if tags.get("Project") != "ColdChainMonitor" or tags.get("Environment") != args.environment:
            raise RuntimeError("Bucket ownership tags mismatch: refusing cleanup")
        objects = []
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
            objects.extend(
                {"Key": o["Key"], "VersionId": o["VersionId"]}
                for o in page.get("Versions", []) + page.get("DeleteMarkers", [])
            )
            if len(objects) > 10000:
                raise RuntimeError("Demo cleanup exceeds 10,000 versions; review scope before deleting")
        for offset in range(0, len(objects), 1000):
            result = s3.delete_objects(
                Bucket=bucket, Delete={"Objects": objects[offset : offset + 1000], "Quiet": True}
            )
            if result.get("Errors"):
                raise RuntimeError("Some object versions could not be deleted; inspect and retry before destroy")
        print("Emptied", bucket, "versions:", len(objects))


if __name__ == "__main__":
    main()
