"""Production tool opt-in never enables development identity or sandbox billing."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def config(**values):
    env = {key: value for key, value in os.environ.items()
           if key not in {"DEBUG", "ENABLE_BETA_TOOLS", "ENABLE_DOCUMENT_TOOLS",
                          "TRUST_PROXY_HEADERS", "STATIC_ROOT"}}
    env.update(DEBUG="0", SECRET_KEY="deployment-settings-test-only-" + "x" * 40,
               DEVELOPMENT_LOGIN_ENABLED="1", LOCAL_SYNC_JOBS="1", COMMERCE_SANDBOX_ENABLED="1")
    env.update(values)
    code = """import json
from config import settings as s
print(json.dumps(dict(debug=s.DEBUG, tools=s.ENABLE_BETA_TOOLS,
    dev=s.DEVELOPMENT_LOGIN_ENABLED, sync=s.LOCAL_SYNC_JOBS,
    sandbox=s.COMMERCE_SANDBOX_ENABLED, static=str(s.STATIC_ROOT),
    proxy=getattr(s,'SECURE_PROXY_SSL_HEADER',None))))
"""
    return json.loads(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=env))


def test_production_tools_are_disabled_without_explicit_opt_in():
    result = config(ENABLE_BETA_TOOLS="1")
    assert not any(result[name] for name in ("debug", "tools", "dev", "sync", "sandbox"))


def test_explicit_production_tools_keep_development_features_disabled():
    result = config(ENABLE_DOCUMENT_TOOLS="1")
    assert result["tools"]
    assert not any(result[name] for name in ("debug", "dev", "sync", "sandbox"))


def test_static_mount_and_proxy_trust_are_explicit_deployment_settings():
    result = config(STATIC_ROOT="/data/static", TRUST_PROXY_HEADERS="1")
    assert result["static"] == "/data/static"
    assert result["proxy"] == ["HTTP_X_FORWARDED_PROTO", "https"]
    assert config()["proxy"] is None
