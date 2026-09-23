#!/usr/bin/env python3
"""Deliver a release over strict host-pinned SSH. No credentials in argv/logs."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("component", choices=("platform", "web"))
parser.add_argument("--bundle", type=Path, default=Path("release.tar.gz"))
args = parser.parse_args()
host, user = os.environ["DEPLOY_HOST"].strip(), os.environ["DEPLOY_USER"].strip()
port = os.environ.get("DEPLOY_PORT", "22")
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,253}", host) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
    raise SystemExit("Invalid deployment hostname/user")
if not port.isdigit() or not 1 <= int(port) <= 65535:
    raise SystemExit("Invalid SSH port")
sha, run, attempt = os.environ["GITHUB_SHA"], os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"]
if not re.fullmatch(r"[a-f0-9]{40}", sha) or not run.isdigit() or not attempt.isdigit():
    raise SystemExit("Invalid release metadata")
relative = f"pdf-master/incoming/{args.component}-{sha}-{run}-{attempt}"
# Only validated identifiers enter the remote shell. User/host stay local argv.
remote = (f'set -eu; umask 077; mkdir -p "$HOME/{relative}"; cd "$HOME/{relative}"; '
          "trap 'rm -f release.tar.gz' EXIT; tar -xf -; "
          "python3 server.py deploy --bundle release.tar.gz")
with tempfile.TemporaryDirectory(prefix="pdfmaster-ssh-") as folder:
    key = Path(folder) / "key"
    known = Path(folder) / "known_hosts"
    key.write_text(os.environ["DEPLOY_SSH_KEY"].rstrip() + "\n")
    known.write_text(os.environ["DEPLOY_KNOWN_HOSTS"].rstrip() + "\n")
    key.chmod(0o600); known.chmod(0o600)
    name = host if port == "22" else f"[{host}]:{port}"
    if subprocess.run(["ssh-keygen", "-F", name, "-f", str(known)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise SystemExit("DEPLOY_KNOWN_HOSTS has no verified key for this host/port.")
    if subprocess.run(["ssh-keygen", "-y", "-P", "", "-f", str(key)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise SystemExit("DEPLOY_SSH_KEY must be a valid deployment key usable without an interactive passphrase.")
    options = ["ssh", "-F", "/dev/null", "-i", str(key), "-p", port,
               "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
               "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known}",
               "-o", "GlobalKnownHostsFile=/dev/null", "-o", "ClearAllForwardings=yes",
               "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15",
               "-o", "ServerAliveCountMax=6", f"{user}@{host}", remote]
    # Spool output to a file so a large transfer cannot deadlock on filled pipes.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(options, stdin=subprocess.PIPE, stdout=output)
        try:
            with tarfile.open(fileobj=process.stdin, mode="w|") as transport:
                transport.add(args.bundle, arcname="release.tar.gz", recursive=False)
                transport.add(Path(__file__).with_name("server.py"), arcname="server.py", recursive=False)
            process.stdin.close()
            code = process.wait(timeout=1500)
        except BaseException:
            process.kill(); process.wait()
            raise
        if code:
            raise SystemExit("SSH deployment failed. Review the server-side error above.")
        output.seek(0)
        lines = output.read(1024 * 1024).decode().strip().splitlines()
        result = json.loads(lines[-1])
    summary = Path(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null"))
    with summary.open("a") as stream:
        stream.write("\n## Server result\n\n" + result["status"].replace("_", " ") + "\n")
        if result["status"].startswith("staged"):
            stream.write("\nNo new stack was activated. Deploy the other repository with the matching API contract.\n")
    print(json.dumps(result))
