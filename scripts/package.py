"""Build byte-identical ZIPs from source and locked runtime dependencies."""

import hashlib
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

root = pathlib.Path(__file__).resolve().parents[1]
out = root / "artifacts"
out.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    target = pathlib.Path(directory)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-compile",
            "--require-hashes",
            "-r",
            str(root / "requirements.lock"),
            "--target",
            str(target),
        ],
        check=True,
    )
    sources = [(p, p.relative_to(target)) for p in target.rglob("*") if p.is_file()]
    sources += [(p, p.relative_to(root)) for p in (root / "app").glob("*.py")]
    with zipfile.ZipFile(out / "app.zip", "w", compression=zipfile.ZIP_STORED, compresslevel=9) as z:
        for source, name in sorted(sources, key=lambda item: str(item[1])):
            if (
                "__pycache__" in str(name)
                or str(name).endswith(".pyc")
                or "/bin/" in str(source)
                or name.name in {"RECORD", "INSTALLER", "REQUESTED", "direct_url.json"}
            ):
                continue
            info = zipfile.ZipInfo(str(name), date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            z.writestr(info, source.read_bytes())
print(hashlib.sha256((out / "app.zip").read_bytes()).hexdigest())
web = out / "web"
web.mkdir(exist_ok=True)
for asset in (root / "app/web").glob("*"):
    if asset.is_file() and asset.suffix in (".html", ".css", ".js"):
        shutil.copyfile(asset, web / asset.name)
