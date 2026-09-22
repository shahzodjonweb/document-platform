#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export DEBUG=1 DEVELOPMENT_LOGIN_ENABLED=1 ENABLE_BETA_TOOLS=1
export LOCAL_SYNC_JOBS="${LOCAL_SYNC_JOBS:-1}" COMMERCE_SANDBOX_ENABLED="${COMMERCE_SANDBOX_ENABLED:-1}"
.venv/bin/python manage.py migrate --noinput
exec .venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload
