#!/usr/bin/env python3
"""Create server-local production secrets once; never overwrite existing keys."""
import argparse
import base64
import os
from pathlib import Path
import re
import secrets

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--component", required=True, choices=("platform", "web"))
parser.add_argument("--port", type=int, default=None, help="Unused loopback HTTP gateway port")
parser.add_argument("--root", type=Path)
parser.add_argument("--enable-document-tools", action="store_true")
args = parser.parse_args()
args.root = args.root or Path.home() / 'pdf-master' / args.component
args.domain = 'pdfmaster-admin.orderdesk.live' if args.component == 'platform' else 'pdfmaster.orderdesk.live'
args.port = args.port or (8311 if args.component == 'platform' else 8310)
if not 1024 <= args.port <= 65535:
    parser.error("Use an available unprivileged port")
args.root.mkdir(parents=True, exist_ok=True, mode=0o700)
values = {
    "DEBUG": "0", "DEVELOPMENT_LOGIN_ENABLED": "0", "LOCAL_SYNC_JOBS": "0",
    "COMMERCE_SANDBOX_ENABLED": "0", "COMMERCE_LIVE_ENABLED": "0",
    "SECRET_KEY": secrets.token_urlsafe(64), "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
    "FILE_SECRET_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    "INTEGRATION_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    "ALLOWED_HOSTS": "pdfmaster-admin.orderdesk.live,pdfmaster.orderdesk.live,127.0.0.1,localhost,api",
    "CSRF_TRUSTED_ORIGINS": "https://pdfmaster-admin.orderdesk.live,https://pdfmaster.orderdesk.live",
    "TELEGRAM_WEBAPP_URL": "https://pdfmaster.orderdesk.live/en/app",
    "PDFMASTER_HTTP_PORT": str(args.port),
    "ENABLE_DOCUMENT_TOOLS": "1" if args.enable_document_tools else "0",
    "COMPOSE_PROFILES": "bot",
}
values['PUBLIC_DOMAIN'] = args.domain
if args.component == 'web':
    values = {'PUBLIC_DOMAIN': args.domain, 'PDFMASTER_HTTP_PORT': str(args.port)}
path = args.root / ".env"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as stream:
    stream.write("# Production secrets: back up this file with the database and private storage.\n")
    stream.write("\n".join(key + "=" + value for key, value in values.items()) + "\n")
print("Created " + str(path) + " with mode 600. No secret values were printed.")
