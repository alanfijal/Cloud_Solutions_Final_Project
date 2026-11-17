"""Verify two independent, hash-locked builds produce identical deployable bytes."""

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    hashes = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(root / "scripts/package.py")], cwd=root, capture_output=True, text=True
        )
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            raise RuntimeError("Package build failed")
        hashes.append(hashlib.sha256((root / "artifacts/app.zip").read_bytes()).hexdigest())
    if len(set(hashes)) != 1:
        raise RuntimeError("Build outputs differed")
    artifact = root / "artifacts/app.zip"
    if artifact.stat().st_size >= 50 * 1024 * 1024:
        raise RuntimeError("Package exceeds direct Lambda upload limit")
    with zipfile.ZipFile(artifact) as archive:
        assert all(not n.startswith("/") and ".." not in Path(n).parts for n in archive.namelist())
        assert not any(n.endswith(".pyc") for n in archive.namelist())
    print("Two builds match:", hashes[0], "bytes:", artifact.stat().st_size)


if __name__ == "__main__":
    main()
