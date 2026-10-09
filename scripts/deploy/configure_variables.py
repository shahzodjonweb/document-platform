#!/usr/bin/env python3
"""Set all four deployment Actions variables in both private repos, reading keys from files."""
import argparse
import json
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--host", required=True)
parser.add_argument("--user", required=True)
parser.add_argument("--key-file", type=Path, required=True)
parser.add_argument("--known-hosts-file", type=Path, required=True)
parser.add_argument("--port", type=int, default=22)
parser.add_argument("--owner", default="shahzodjonweb")
parser.add_argument("--storage", choices=("variables", "secrets"), default="secrets")
args = parser.parse_args()
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,253}", args.host) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", args.user):
    parser.error("Invalid host/user")
if not re.fullmatch(r"[A-Za-z0-9-]+", args.owner) or not 1 <= args.port <= 65535:
    parser.error("Invalid owner/port")
lookup = args.host if args.port == 22 else f"[{args.host}]:{args.port}"
for command in (
    ["ssh-keygen", "-y", "-P", "", "-f", str(args.key_file)],
    ["ssh-keygen", "-F", lookup, "-f", str(args.known_hosts_file)],
):
    if subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        parser.error("Invalid key or no verified known-hosts entry for the target")
values = {"DEPLOY_HOST": args.host, "DEPLOY_USER": args.user,
          "DEPLOY_SSH_KEY": args.key_file.read_text(),
          "DEPLOY_KNOWN_HOSTS": args.known_hosts_file.read_text()}
storage = "variable" if args.storage == "variables" else "secret"
for name in ("document-platform", "document-web"):
    repo = args.owner + "/" + name
    details = json.loads(subprocess.check_output(["gh", "repo", "view", repo, "--json", "isPrivate"]))
    if not details["isPrivate"]:
        raise SystemExit("Refusing to configure deployment credentials in a public repository: " + repo)
    for key, value in values.items():
        subprocess.run(["gh", storage, "set", key, "--repo", repo], input=value.encode(), check=True)
    # Set the port even when it is 22, so a previous custom value cannot linger.
    subprocess.run(["gh", "variable", "set", "DEPLOY_PORT", "--repo", repo, "--body", str(args.port)], check=True)
    actual = json.loads(subprocess.check_output(["gh", storage, "list", "--repo", repo, "--json", "name"]))
    if not set(values).issubset({item["name"] for item in actual}):
        raise SystemExit("Variable-name verification failed: " + repo)
    print(repo + ": all four deployment setting names verified.")
