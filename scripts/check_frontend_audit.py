"""Fail on new high-severity frontend advisories; narrowly track one build-only issue."""

import json
import subprocess
from datetime import date
from pathlib import Path

EXCEPTION_URL = "https://github.com/advisories/GHSA-fc5q-39xc-vjpf"
EXPIRY = date(2026, 12, 18)


def main():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["npm", "audit", "--json"], cwd=root / "app/web", capture_output=True, text=True)
    report = json.loads(result.stdout)
    if "error" in report:
        raise RuntimeError("npm vulnerability service unavailable; audit was not completed")
    vulnerabilities = report.get("vulnerabilities", {})
    accepted = set()
    for name, item in vulnerabilities.items():
        if item["severity"] not in ("high", "critical"):
            continue
        # Vite's glob patterns are trusted repository configuration. This package
        # is absent from the browser bundle, and no Vite server is deployed.
        if name == "picomatch" and not item.get("isDirect") and date.today() <= EXPIRY:
            advisories = [v for v in item.get("via", []) if isinstance(v, dict)]
            if advisories and all(a.get("url") == EXCEPTION_URL for a in advisories):
                accepted.add(name)
    changed = True
    while changed:
        changed = False
        for name, item in vulnerabilities.items():
            via = item.get("via", [])
            if name not in accepted and via and all(isinstance(v, str) and v in accepted for v in via):
                accepted.add(name)
                changed = True
    unresolved = [
        name
        for name, item in vulnerabilities.items()
        if item["severity"] in ("high", "critical") and name not in accepted
    ]
    if unresolved:
        raise RuntimeError("Unreviewed frontend security findings: " + ", ".join(unresolved))
    print("Frontend audit checked; build-only unpatched picomatch exception expires", EXPIRY.isoformat())
    if accepted:
        print("Affected build dependency chain:", ", ".join(sorted(accepted)))


if __name__ == "__main__":
    main()
