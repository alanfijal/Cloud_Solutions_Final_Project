"""Local plan/review/apply with temporary credentials and saved-plan integrity checks."""

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import time

from aws_local import ACCOUNT, terraform_env

ROOT = pathlib.Path(__file__).resolve().parents[1]


def fingerprint():
    digest = hashlib.sha256()
    files = []
    for directory in ("app", "simulator", "scripts", "infra"):
        for path in (ROOT / directory).rglob("*"):
            if not path.is_file() or any(
                x in path.parts for x in (".terraform", "__pycache__", "node_modules", "dist")
            ):
                continue
            if path.suffix in (
                ".py",
                ".tf",
                ".hcl",
                ".toml",
                ".html",
                ".css",
                ".js",
                ".svg",
                ".ts",
                ".tsx",
                ".json",
            ) or path.name.endswith(("tfvars", "tfvars.json")):
                files.append(path)
    files += [ROOT / name for name in ("requirements.lock", ".terraform-version")]
    files += [ROOT / "artifacts/app.zip"] if (ROOT / "artifacts/app.zip").exists() else []
    files += [p for p in (ROOT / "artifacts/web").rglob("*") if p.is_file()]
    for path in sorted(set(files)):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def commit():
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "UNCOMMITTED"


def worktree_clean():
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, capture_output=True, text=True
    )
    return result.returncode == 0 and not result.stdout.strip()


def verify_saved_plan(meta, plan, revision, source_hash, account, data_loss, now, *, clean):
    if account != ACCOUNT:
        raise ValueError("Correct account confirmation is required after deployment approval")
    if meta["preview_only"]:
        raise ValueError("Preview cannot be applied; create and review a real-backend plan")
    if meta["destroy"] and not data_loss:
        raise ValueError("Destroy requires explicit data-loss confirmation")
    if meta["commit"] == "UNCOMMITTED" or revision != meta["commit"]:
        raise ValueError("A reviewed plan for the current committed revision is required")
    if not meta.get("clean_worktree", False) or not clean:
        raise ValueError("Commit source changes, then regenerate and review the plan")
    if source_hash != meta["source_sha256"] or hashlib.sha256(plan.read_bytes()).hexdigest() != meta["plan_sha256"]:
        raise ValueError("Source, configuration, package or plan changed; regenerate and review")
    if not 0 <= now - meta["created_at"] <= 86400:
        raise ValueError("Plan time is invalid or older than 24 hours; refresh and review")


def prepare_preview(source, destination):
    """Copy root configuration without a live backend, regardless of .tf filenames."""
    for path in source.glob("*"):
        if not path.is_file() or path.suffix not in (".tf", ".json", ".hcl"):
            continue
        target = destination / path.name
        if path.suffix == ".tf":
            target.write_text(re.sub(r'backend\s+"s3"\s*\{\s*\}', "", path.read_text()))
        else:
            target.write_bytes(path.read_bytes())


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument("root", choices=["bootstrap", "dev", "demo"])
    p.add_argument("command", choices=["init", "plan", "preview", "show", "apply", "destroy-plan", "output"])
    p.add_argument("--confirm-account")
    p.add_argument("--confirm-data-loss", action="store_true")
    args = p.parse_args()
    root = ROOT / "infra" / ("bootstrap" if args.root == "bootstrap" else "environments/" + args.root)
    plan = ROOT / ".local" / (args.root + ".tfplan")
    manifest = plan.with_suffix(".manifest.json")
    plan.parent.mkdir(exist_ok=True)
    env = terraform_env()
    base = ["terraform", "-chdir=" + str(root)]
    if args.command == "init":
        command = ["init", "-input=false", "-lockfile=readonly"]
        if args.root != "bootstrap":
            command.append("-backend-config=backend.hcl")
        subprocess.run(base + command, env=env, check=True)
        return
    if args.command in ("plan", "preview", "destroy-plan"):
        if args.root == "bootstrap" and args.command == "destroy-plan":
            p.error(
                "Backend cleanup requires separate owner approval and state export; ordinary destroy covers the application only"
            )
        command = ["plan", "-input=false", "-lock-timeout=60s", "-var-file=local.tfvars.json", "-out=" + str(plan)]
        if args.command == "destroy-plan":
            command.append("-destroy")
        if args.command == "preview":
            if args.root == "bootstrap":
                p.error("Bootstrap uses plan; preview is only for the application before its backend exists")
            # Preview is a separate copy without a backend block, using isolated local state.
            import tempfile

            with tempfile.TemporaryDirectory(prefix="coldchain-preview-", dir=ROOT / "infra/environments") as temporary:
                preview = pathlib.Path(temporary)
                prepare_preview(root, preview)
                preview_base = ["terraform", "-chdir=" + str(preview)]
                subprocess.run(
                    preview_base + ["init", "-backend=false", "-input=false", "-lockfile=readonly"], env=env, check=True
                )
                subprocess.run(preview_base + command, env=env, check=True)
                rendered = subprocess.check_output(preview_base + ["show", "-json", str(plan)], env=env)
            # Reviewable resource preview, explicitly never applicable to the real backend.
        else:
            subprocess.run(base + command, env=env, check=True)
        if args.command != "preview":
            rendered = subprocess.check_output(base + ["show", "-json", str(plan)], env=env)
        plan.with_suffix(".plan.json").write_bytes(rendered)
        changes = json.loads(rendered).get("resource_changes", [])
        summary = [
            {"address": r["address"], "actions": r["change"]["actions"]}
            for r in changes
            if r["change"]["actions"] != ["no-op"]
        ]
        metadata = {
            "commit": commit(),
            "clean_worktree": worktree_clean(),
            "source_sha256": fingerprint(),
            "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
            "created_at": int(time.time()),
            "destroy": args.command == "destroy-plan",
            "preview_only": args.command == "preview",
            "changes": summary,
        }
        manifest.write_text(json.dumps(metadata, indent=2))
        print(json.dumps({"commit": metadata["commit"], "changes": summary, "manifest": str(manifest)}, indent=2))
    elif args.command == "apply":
        meta = json.loads(manifest.read_text())
        try:
            verify_saved_plan(
                meta,
                plan,
                commit(),
                fingerprint(),
                args.confirm_account,
                args.confirm_data_loss,
                int(time.time()),
                clean=worktree_clean(),
            )
        except ValueError as exc:
            p.error(str(exc))
        if input("Type APPLY REVIEWED PLAN to continue: ") != "APPLY REVIEWED PLAN":
            p.error("Cancelled")
        subprocess.run(base + ["apply", "-input=false", "-lock-timeout=60s", str(plan)], env=env, check=True)
    elif args.command == "show":
        subprocess.run(base + ["show", str(plan)], env=env, check=True)
    else:
        subprocess.run(base + ["output", "-json"], env=env, check=True)


if __name__ == "__main__":
    main()
