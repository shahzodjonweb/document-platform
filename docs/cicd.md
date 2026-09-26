# Independent deployments on orderdesk.live

| Repository | URL | Docker project | Server directory | Loopback gateway |
| --- | --- | --- | --- | --- |
| document-platform | https://pdfmaster-admin.orderdesk.live/ops/login | pdfmaster-platform | ~/pdf-master/platform | 127.0.0.1:8311 |
| document-web | https://pdfmaster.orderdesk.live/en/app | pdfmaster-web | ~/pdf-master/web | 127.0.0.1:8310 |

The platform owns the API, admin, PostgreSQL, Redis, private files, workers and Telegram bot. The web project owns only its customer application and gateway. Each has its own Compose network, environment, deployment lock, release history and rollback. Web deployments never run platform migrations or touch its containers/volumes; platform deployments never change web containers. Neither deployer modifies other server projects or prunes Docker globally.

The customer app calls the API through its same-origin `/api` proxy to `https://pdfmaster-admin.orderdesk.live`. It shares no Docker network with the platform. API availability remains an application dependency; use backward-compatible API changes and migrations when releasing independently. A backend restart can briefly interrupt API requests, while the web container continues serving the interface.

## GitHub credentials

Both repositories accept the following settings from **Settings → Secrets and variables → Actions**. The existing SSH key can remain in Secrets; repository Variables are also supported. Values pass into a reusable workflow as masked secret inputs before any step environment is logged. A key stored as a Variable remains readable in variable settings; masking does not change that storage behavior.

| Setting | Value |
| --- | --- |
| DEPLOY_HOST | 77.42.34.241 |
| DEPLOY_USER | orderdesk-deploy |
| DEPLOY_SSH_KEY | Private deployment key whose public half is authorized for orderdesk-deploy on this server |
| DEPLOY_KNOWN_HOSTS | Verified OpenSSH known-hosts entry for the host and SSH port |

No SSH password, registry token, or server GitHub checkout is used. `DEPLOY_PORT` is an optional Actions Variable, default 22. `DEPLOY_PLATFORM` defaults to `linux/amd64`; use `linux/arm64` for an ARM host.

The configuration helper can populate both repositories from local key files without printing their contents:

```sh
python3 scripts/deploy/configure_variables.py --storage secrets \
  --host 77.42.34.241 --user orderdesk-deploy \
  --key-file /absolute/path/deployment-key \
  --known-hosts-file /absolute/path/verified-known-hosts
```

Omit `--storage secrets` to store the values as Variables. Confirm the host fingerprint through an existing trusted record or the server provider's console; do not trust an unverified key scan. The matching public key must be installed in the `orderdesk-deploy` account’s `~/.ssh/authorized_keys`. A valid private key in GitHub alone does not authorize it on the server.

## Build, activation and rollback

CI validates each repository, builds an immutable image and boots **its own complete production Compose stack**, including gateway routes. The platform runs all application tests on SQLite and PostgreSQL. Both run deployment tests covering independent updates, independent locks, failed release recovery, path traversal, archive tampering and stale workflow delivery.

Passing `main` releases transfer an image archive over host-pinned SSH. Release protocol v2 rejects component mismatches. Each repository deploys immediately without waiting for the other repository's image or API checksum. A delayed older run cannot supersede its newer release.

On first delivery, `init_environment.py` creates only that component's environment, mode 600, without overwriting existing keys. Platform application and encryption keys are random. Development login, test synchronization and sandbox commerce remain disabled. The platform enables document tools and starts a bot process that waits for credentials in Admin Integrations.

Only platform deployments back up PostgreSQL, run forward migrations and collect static assets. Each release starts its own services, refreshes only its own gateway and verifies its routes. A failed release restores the previous healthy image and, for the platform, static assets. Database migrations are never reversed automatically. Rollback is scoped explicitly:

```sh
python3 ~/pdf-master/platform/incoming/RELEASE_DIRECTORY/server.py rollback --component platform
python3 ~/pdf-master/web/incoming/RELEASE_DIRECTORY/server.py rollback --component web
```

The first release has no previous image to restore. The persistent directories contain `.env`, `.owner`, `state.json`, `deploy.lock`, `releases/` and `incoming/`. Platform database dumps are in `~/pdf-master/platform/backups/`.

Each deployment reclaims its own disk before unpacking and again once the new release is active: it keeps the active release, the previous one rollback depends on, any pending one, and the five most recent database dumps and delivered script directories. Everything older is removed along with the image only that release named. This stays inside `~/pdf-master/<component>/` and never prunes Docker globally, so other projects on the host are untouched. An image a running container still uses is refused by Docker and left alone, and a housekeeping failure never fails a release. Off-server backup retention is still yours to configure — five pre-activation dumps is a rollback aid, not an archive.

If a disk has already filled, that reclaim cannot save you: the deploy scripts have to land on the server before any of it runs, and a full disk stops even that. Break the deadlock once with `scripts/deploy/reclaim.py`, which applies the same policy by hand and reports before it removes anything.

```
python3 reclaim.py --component platform           # report only
python3 reclaim.py --component platform --apply   # remove
```

Copy it next to the other deploy scripts, or paste it into a heredoc if there is no room to scp. After one run the protocol keeps the component bounded on its own. Preserve the platform environment's encryption keys together with database and private-file backups.

## HTTPS alongside existing projects

The host already serves other projects. Inspect the current TLS proxy and container inventory before integration. Keep their files, routes, container IDs and start times unchanged. Add only the two new PDF Master host routes; never replace the existing proxy configuration, stop its containers, or run a global Compose down/prune command.

For a host Caddy instance, each repository supplies its own `infra/production/Caddyfile` site block pointing at its loopback gateway. Add those blocks through the server's existing include mechanism and validate/reload gracefully. Caddy can provision TLS for the two DNS hostnames once they resolve to this server. If Caddy is containerized, use the repository's `proxy-network.example.yaml` as that component's server-owned `compose.override.yaml`; attach only its gateway to the existing ingress network and route to `pdfmaster-platform-gateway:8080` or `pdfmaster-web-gateway:8080`. The database and application networks stay separate.

A server-owned override is read only by its own component's deployer. TLS proxy changes happen during site setup, not during routine image deployments. The deployers never reconfigure the shared proxy.

## Administration and Telegram

On the server, select the platform release for management commands:

```sh
cd ~/pdf-master/platform
release=$(python3 -c 'import json; print(json.load(open("state.json"))["active"]["release_id"])')
export PDFMASTER_ENV_FILE="$PWD/.env"
export PDFMASTER_IMAGE=$(python3 -c 'import json; print(json.load(open("state.json"))["active"]["image"])')
docker compose -p pdfmaster-platform --env-file .env \
  -f "releases/$release/stack/compose.yaml" \
  exec api python manage.py setup_staff your-admin --role Administrator
```

Include an existing `compose.override.yaml` with another `-f` before `exec`. Enroll password and TOTP interactively over SSH; do not publish enrollment credentials in CI logs. Configure Telegram token/username and AI provider credentials in Admin Integrations. The bot container waits without contacting Telegram until polling credentials are configured, then starts automatically. If replacing an already-running bot's token, restart only the platform `bot` service. Provider/payment credentials and reviewed production offers remain separate configuration.

Manual operations use the `PDF Master server operations` workflow. Its inventory operation is read-only, uses the same pinned SSH credentials and prints routing/container metadata rather than environments or keys. A successful build with missing credentials is not a deployment; inspect the deployment job's final server result and public HTTPS routes.
