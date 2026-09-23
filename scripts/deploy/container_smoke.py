#!/usr/bin/env python3
"""Smoke-test the real built image without exposing a host port."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument("component", choices=("platform", "web"))
parser.add_argument("image")
args = parser.parse_args()
repo = Path(__file__).resolve().parents[2]
name = "pdfmaster-ci-" + os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"]

def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)

def wait(command):
    for _ in range(45):
        if subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return
        time.sleep(2)
    raise SystemExit("Container readiness check failed")

if args.component == "web":
    try:
        run(["docker", "run", "-d", "--name", name, "--read-only", "--tmpfs", "/tmp", args.image],
            stdout=subprocess.DEVNULL)
        wait(["docker", "exec", name, "node", "-e",
              "fetch('http://127.0.0.1:3000/en/app').then(async r=>{if(!r.ok||!(await r.text()).includes('PDF Master'))process.exit(1)}).catch(()=>process.exit(1))"])
    finally:
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL)
else:
    with tempfile.TemporaryDirectory() as temp:
        staging = Path(temp)
        run(["python3", str(repo / "scripts/deploy/init_environment.py"),
             "--domain", "ci.invalid", "--root", str(staging)])
        env = {**os.environ, "PLATFORM_IMAGE": args.image,
               "WEB_IMAGE": "pdfmaster-web:configuration-validation-only",
               "PDFMASTER_ENV_FILE": str(staging / ".env")}
        compose = ["docker", "compose", "-p", name, "--env-file", str(staging / ".env"),
                   "-f", str(repo / "infra/production/compose.yaml")]
        try:
            run(compose + ["config", "--quiet"], env=env)
            run(compose + ["up", "-d", "--wait", "--wait-timeout", "120", "db", "redis"], env=env)
            run(compose + ["run", "--rm", "--no-deps", "init"], env=env)
            run(compose + ["up", "-d", "--wait", "--wait-timeout", "180", "api", "worker", "batches", "cleanup"], env=env)
            code = """import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import urllib.request
from pathlib import Path
from django.conf import settings
import django
django.setup()
assert not settings.DEBUG and not settings.DEVELOPMENT_LOGIN_ENABLED and not settings.LOCAL_SYNC_JOBS
for url in ['/api/v1/health','/api/v1/plans','/ops/login']:
    assert urllib.request.urlopen('http://127.0.0.1:8000'+url,timeout=10).status==200
assert Path('/data/static/ops/main.css').is_file()
print('Production image: database, migrations, API, admin, static assets, and workers verified.')
"""
            run(compose + ["exec", "-T", "api", "python", "-c", code],
                env=env)
        finally:
            # This is exclusively the ephemeral CI project, never pdfmaster.
            subprocess.run(compose + ["down", "--volumes"], env=env, stdout=subprocess.DEVNULL)
print("Container smoke check passed.")
