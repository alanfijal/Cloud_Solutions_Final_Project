"""Export one already-provisioned device credential for secure gateway setup."""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", choices=[f"unit-{i}" for i in range(1, 6)], required=True)
    parser.add_argument("--source", type=Path, default=Path(".local/device-credentials-dev.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(Path(".local").resolve()):
        parser.error("Write the credential only inside the ignored .local directory")
    credential = json.loads(args.source.read_text())[args.unit]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump({args.unit: credential}, output)
    print("Exported one device credential to", args.output, "with mode 0600. Transfer it securely; do not commit it.")


if __name__ == "__main__":
    main()
