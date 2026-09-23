# CI/CD and server setup

Both private repositories deploy into one isolated Docker Compose project named `pdfmaster`. The platform image runs the API, admin panel, document workers and optional Telegram bot; the web image serves the customer application. GitHub builds and tests the images and transfers release archives over SSH. The server needs neither a GitHub token nor access to a private image registry.

## Required GitHub Actions secrets

Add these **repository secrets to both repositories**, using the same target server and account:

| Secret | Value |
| --- | --- |
| `DEPLOY_HOST` | Server hostname or IP address, without a URL scheme |
| `DEPLOY_USER` | SSH account with Docker access |
| `DEPLOY_SSH_KEY` | Complete private deployment key, usable without an interactive passphrase |
| `DEPLOY_KNOWN_HOSTS` | Verified OpenSSH known-hosts entry for that host and SSH port |

Settings: [platform secrets](https://github.com/shahzodjonweb/document-platform/settings/secrets/actions), [web secrets](https://github.com/shahzodjonweb/document-web/settings/secrets/actions).

Use a dedicated deployment key whose public half is installed in the server account's `authorized_keys`. Confirm the host fingerprint through your server provider's console or an existing trusted record before supplying the known-hosts file. An unverified `ssh-keyscan` result alone does not establish trust. Never commit or paste private keys into chat.

With authenticated GitHub CLI access, this helper sets and verifies the four names in **both** private repositories. It reads key contents from files and sends secret values through standard input:

```sh
python3 scripts/deploy/configure_secrets.py \
  --host your-server.example --user deploy \
  --key-file /absolute/path/deployment-key \
  --known-hosts-file /absolute/path/verified-known-hosts
```

For a nonstandard SSH port add `--port 2222`; this also sets the normal Actions variable `DEPLOY_PORT`. Its known-hosts entry must match `[host]:2222`. Set the normal Actions variable `DEPLOY_PLATFORM=linux/arm64` in both repositories for an ARM server; the default is `linux/amd64`.

Without all four secrets, CI still tests and packages the application, and the deployment job explicitly reports **Deployment not configured**. It does not connect to a server. A green CI run with that message does not mean the website was deployed.

## Pipeline behavior

Pull requests run checks and build and smoke-test the real Docker images. Platform checks include SQLite and PostgreSQL application tests, schema consistency, migration checks and release transaction tests. Web checks include the API/catalog contract, type checking, production build and release transaction tests.

On `main`, a passing build also produces an immutable release archive, retained in GitHub for one day, and deploys if credentials are configured. Deployments from the two repositories share a server-side lock. A delayed older workflow cannot replace a newer release. The first component waits for the other; changes to the public API checksum wait for a matching pair before activation. The last healthy pair remains active while a new pair is pending.

The deployer verifies archive checksums and image identity, starts only the `pdfmaster` database and Redis, backs up the database, runs migrations and collects static assets, starts services, then checks API and web routes through the gateway. A normal health or migration failure restores the previous images and static assets when a healthy previous release exists. The first deployment has no previous release to restore. Database migrations are never automatically reversed; use backward-compatible migrations.

## Prepare the server once

Requirements: Linux, Python 3.10+, Docker with Compose 2.24+, SSH, tar, and a deployment account with Docker access. Inspect free RAM, disk, ports and existing containers before activation. Document processing and LibreOffice need substantially more resources than a static website; the Compose file sets explicit per-service limits. Choose a free loopback port (default `8310`) and a new domain/subdomain.

Copy `scripts/deploy/init_environment.py` to the server using your verified SSH connection, then run there:

```sh
python3 /path/to/init_environment.py --domain pdf.your-domain.com --port 8310
```

This creates `~/pdf-master/.env` with random application, database and encryption keys and mode `600`. It refuses to overwrite an existing environment. Keep this file on the server and preserve it with backups: encrypted data requires its original keys.

Development login, synchronous test jobs and sandbox commerce are forced off in production. Document tools start disabled; enable `ENABLE_DOCUMENT_TOOLS=1` in the server environment only when ready to offer the processing features (or use the initializer's explicit `--enable-document-tools` option). This switch does not enable development authentication. Configure provider credentials through the admin Integrations page. Enabling CI/CD does not complete live provider, payment, parser containment or production acceptance work.

Server layout:

```text
~/pdf-master/
  .env                     # persistent application secrets, mode 600
  compose.override.yaml    # optional server-owned proxy integration
  deploy.lock              # shared deployment lock
  state.json               # active, previous and pending release metadata
  backups/                 # database dumps before deployments
  releases/                # immutable component manifests and platform stack files
  incoming/                # deployment helpers; image bundles removed after delivery
```

This starts a fresh production database; local demonstration records are not copied. Database, private files, static assets and Redis use project-scoped Docker volumes. The scripts never prune Docker globally or remove production data volumes. Arrange retention, encrypted off-server backups and restore drills for the database, private files and encryption keys; old releases and backups are intentionally not deleted automatically.

## Route a separate domain alongside the existing project

Only the gateway publishes a port, bound to `127.0.0.1:8310`. Database, Redis, API and web ports stay inside Docker. Project-scoped resources keep this deployment separate from another Compose application.

For a reverse proxy running on the host, adapt [host-nginx.example.conf](../infra/production/host-nginx.example.conf) as a **new** virtual host and configure its domain and TLS certificate. Preserve the existing project's configuration. The proxy must overwrite `X-Forwarded-Proto` with its actual connection scheme.

For a reverse proxy already running in Docker, adapt [proxy-network.example.yaml](../infra/production/proxy-network.example.yaml) into `~/pdf-master/compose.override.yaml` and set `PDFMASTER_PROXY_NETWORK` in the server environment. Join only the gateway to the existing proxy network and route the new hostname to `http://pdfmaster-gateway:8080`. Keep the default PDF Master network. The proxy must terminate HTTPS and overwrite forwarded protocol headers. This optional override is owned by the server and is not replaced by releases.

## Activate and administer

After the server environment, HTTPS routing and four repository secrets are configured, run both workflows (or push to `main`):

```sh
gh workflow run ci.yml --repo shahzodjonweb/document-platform --ref main
gh workflow run ci.yml --repo shahzodjonweb/document-web --ref main
```

The first delivery reports a staged release; the second matching component activates the stack. Verify the deployment job's server result and the public website. To run management commands against the active release, use this on the server:

```sh
cd ~/pdf-master
platform_release=$(python3 -c 'import json; print(json.load(open("state.json"))["active"]["platform"]["release_id"])')
export PDFMASTER_ENV_FILE="$PWD/.env"
export PLATFORM_IMAGE=$(python3 -c 'import json; print(json.load(open("state.json"))["active"]["platform"]["image"])')
export WEB_IMAGE=$(python3 -c 'import json; print(json.load(open("state.json"))["active"]["web"]["image"])')
docker compose -p pdfmaster --env-file .env \
  -f "releases/platform/$platform_release/stack/compose.yaml" \
  exec api python manage.py setup_staff your-admin --role Administrator
```

Include `-f "$PWD/compose.override.yaml"` before `exec` if using the optional override. Complete staff password/TOTP enrollment interactively over SSH, not in CI logs. The admin panel is at `https://YOUR_DOMAIN/ops/login`; the customer app is at `https://YOUR_DOMAIN/en/app`.

Configure the Telegram token and username in **Admin → Integrations**. Then set `COMPOSE_PROFILES=bot` in the server environment and rerun a workflow to start the polling bot container. The local-development process controls remain disabled in production; Docker manages the bot lifecycle.

## Rollback and investigation

Use a delivered helper from `incoming/` on the server:

```sh
python3 ~/pdf-master/incoming/RELEASE_DIRECTORY/server.py rollback
```

This restores the recorded previous images and staff assets. It does not restore the database or undo migrations. Destructive schema changes require a separately planned data recovery procedure. Keep deploy logs and inspect service logs on the server; do not publish rendered Compose configuration or the environment file, which contain secrets. If a connection or runner is interrupted, inspect `state.json` and actual container health before retrying.

The generic deployment helpers are intentionally duplicated in both repositories so each can deliver independently. Keep their protocol and tests synchronized when changing them. The platform repository alone owns the production Compose configuration.

References: [GitHub Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets), [Compose in production](https://docs.docker.com/compose/how-tos/production/).
