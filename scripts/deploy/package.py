#!/usr/bin/env python3
"""Package the already-tested local Docker image; uses no registry credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from server import digest, validate_manifest

parser = argparse.ArgumentParser()
parser.add_argument("component", choices=("platform", "web"))
parser.add_argument("--output", type=Path, default=Path("release.tar.gz"))
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
commit = os.environ["GITHUB_SHA"]
run = int(os.environ["GITHUB_RUN_ID"])
attempt = int(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
if not re.fullmatch(r"[0-9a-f]{40}", commit):
    raise SystemExit("Invalid commit")
release_id = f"{commit}-{run}-{attempt}"
image = f"pdfmaster-{args.component}:{release_id}"
info = json.loads(subprocess.check_output(["docker", "image", "inspect", image]))[0]
schema = root / ("contracts/public.openapi.json" if args.component == "platform" else "generated/api/public.openapi.json")
with tempfile.TemporaryDirectory() as directory:
    staging = Path(directory)
    archive = staging / "image.tar.gz"
    # gzip -n avoids embedding source names/timestamps and streams large images.
    with archive.open("wb") as output:
        saving = subprocess.Popen(["docker", "save", image], stdout=subprocess.PIPE)
        compressed = subprocess.run(["gzip", "-n", "-1"], stdin=saving.stdout, stdout=output)
        saving.stdout.close()
        if compressed.returncode or saving.wait():
            raise SystemExit("Docker image export failed")
    meta = validate_manifest({
        "protocol": 1, "component": args.component, "commit": commit,
        "run_id": run, "run_attempt": attempt, "release_id": release_id,
        "image": image, "image_id": info["Id"], "architecture": info["Architecture"],
        "archive_sha256": digest(archive), "contract_sha256": digest(schema),
    })
    (staging / "release.json").write_text(json.dumps(meta))
    names = ["release.json", "image.tar.gz"]
    if args.component == "platform":
        (staging / "stack").mkdir()
        for name in ("compose.yaml", "nginx.conf"):
            shutil.copyfile(root / "infra/production" / name, staging / "stack" / name)
            names.append("stack/" + name)
    with tarfile.open(args.output, "w:gz", compresslevel=1) as bundle:
        for name in names:
            bundle.add(staging / name, arcname=name, recursive=False)
print("Packaged " + args.component + " release " + release_id)
