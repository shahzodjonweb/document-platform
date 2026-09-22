#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export DEBUG=1 DEVELOPMENT_LOGIN_ENABLED=1 ENABLE_BETA_TOOLS=1 LOCAL_SYNC_JOBS=1
export SECRET_KEY="${SECRET_KEY:-local-development-change-before-deployment}"
.venv/bin/python manage.py migrate --noinput
exec .venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload
