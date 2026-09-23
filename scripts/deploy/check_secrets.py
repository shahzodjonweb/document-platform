#!/usr/bin/env python3
"""Expose readiness only; never print secret values or create placeholders."""
import os
from pathlib import Path

required = ("DEPLOY_HOST", "DEPLOY_USER", "DEPLOY_SSH_KEY", "DEPLOY_KNOWN_HOSTS")
missing = [name for name in required if not os.environ.get(name, "").strip()]
ready = not missing
with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
    output.write("configured=" + str(ready).lower() + "\n")
message = ("Deployment secrets are configured." if ready else
           "Deployment is not configured. Add these repository Actions secrets: " + ", ".join(missing) +
           ". CI and image checks still run; no server connection was attempted.")
with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
    summary.write("## Deployment readiness\n\n" + message + "\n")
if missing:
    print("::notice title=Deployment not configured::" + message)
