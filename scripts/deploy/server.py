#!/usr/bin/env python3
"""PDF Master release protocol v1; identical in both application repositories.

Receives only CI-built images over authenticated SSH. Never runs git on the
server, edits another Compose project, prunes Docker, or deletes data volumes.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

PROJECT = "pdfmaster"
MAX_BUNDLE = 3 * 1024**3
SERVICES = ["api", "worker", "batches", "cleanup", "web"]


class DeploymentError(Exception):
    pass


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def command(args, *, env=None, input_stream=None, output_stream=None):
    # Capture errors: do not print commands/env or Docker configuration containing
    # database credentials. Operators can inspect service logs on their server.
    result = subprocess.run(args, env=env, stdin=input_stream,
                            stdout=output_stream or subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=900)
    if result.returncode:
        raise DeploymentError("Command failed: " + " ".join(args[:3]) +
                              ". Inspect PDF Master service logs on the server.")
    return result.stdout.decode().strip() if output_stream is None else ""


def environment(root):
    path = root / ".env"
    if not path.is_file() or path.is_symlink():
        raise DeploymentError("Create ~/pdf-master/.env with init_environment.py first.")
    if path.stat().st_mode & 0o077:
        raise DeploymentError("Set production .env permissions to 600.")
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*=.*", line):
            raise DeploymentError("Production .env requires plain KEY=value entries.")
        key, value = line.split("=", 1)
        if key in values:
            raise DeploymentError("Production .env contains duplicate keys.")
        values[key] = value
    for key in ("SECRET_KEY", "POSTGRES_PASSWORD", "FILE_SECRET_KEY", "INTEGRATION_ENCRYPTION_KEY"):
        if len(values.get(key, "")) < 32 or "replace" in values[key].lower():
            raise DeploymentError("Missing or placeholder production secret: " + key)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", values["POSTGRES_PASSWORD"]):
        raise DeploymentError("POSTGRES_PASSWORD must be URL-safe letters, digits, _ or -.")
    for key in ("DEBUG", "DEVELOPMENT_LOGIN_ENABLED", "LOCAL_SYNC_JOBS", "COMMERCE_SANDBOX_ENABLED"):
        if values.get(key, "0") != "0":
            raise DeploymentError("Development settings must remain disabled: " + key)
    origins = values.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if not origins or any(not re.fullmatch(r"https://[a-zA-Z0-9.-]+(?::[0-9]+)?", x) for x in origins):
        raise DeploymentError("Set explicit HTTPS CSRF_TRUSTED_ORIGINS.")
    if not values.get("ALLOWED_HOSTS") or "*" in values["ALLOWED_HOSTS"]:
        raise DeploymentError("Set explicit ALLOWED_HOSTS.")
    port = values.get("PDFMASTER_HTTP_PORT", "8310")
    if not port.isdigit() or not 1024 <= int(port) <= 65535:
        raise DeploymentError("PDFMASTER_HTTP_PORT must be an unprivileged port.")
    if values.get("COMPOSE_PROFILES", "") not in ("", "bot"):
        raise DeploymentError("Only the optional bot profile is supported.")
    return values


def validate_manifest(meta):
    if meta.get("protocol") != 1 or meta.get("component") not in ("platform", "web"):
        raise DeploymentError("Unsupported release protocol/component.")
    if not re.fullmatch(r"[0-9a-f]{40}", meta.get("commit", "")):
        raise DeploymentError("Invalid commit.")
    for field in ("contract_sha256", "archive_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", meta.get(field, "")):
            raise DeploymentError("Invalid release checksum.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", meta.get("image_id", "")):
        raise DeploymentError("Invalid Docker image identity.")
    if type(meta.get("run_id")) is not int or meta["run_id"] <= 0 or type(meta.get("run_attempt")) is not int or meta["run_attempt"] <= 0:
        raise DeploymentError("Invalid workflow run identifier.")
    release_id = f"{meta['commit']}-{meta['run_id']}-{meta['run_attempt']}"
    if meta.get("release_id") != release_id:
        raise DeploymentError("Invalid release identifier.")
    expected = f"pdfmaster-{meta['component']}:{release_id}"
    if meta.get("image") != expected or meta.get("architecture") not in ("amd64", "arm64"):
        raise DeploymentError("Invalid image name/architecture.")
    if type(meta.get("run_id")) is not int or meta["run_id"] <= 0:
        raise DeploymentError("Invalid workflow run identifier.")
    return meta


def unpack(bundle, destination):
    # The image is opaque Docker data; stack configuration is supplied only by
    # the platform release. No links, path traversal, devices or duplicate names.
    with tarfile.open(bundle, "r:gz") as archive:
        members = archive.getmembers()
        names = [x.name for x in members]
        allowed = {"release.json", "image.tar.gz", "stack/compose.yaml", "stack/nginx.conf"}
        if len(names) != len(set(names)) or set(names) - allowed or sum(x.size for x in members) > MAX_BUNDLE:
            raise DeploymentError("Invalid/oversized release archive.")
        if not {"release.json", "image.tar.gz"}.issubset(names) or any(not x.isfile() for x in members):
            raise DeploymentError("Release archive must contain regular files only.")
        for member in members:
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            os.chmod(target, 0o600)
    meta = validate_manifest(read_json(destination / "release.json"))
    has_stack = {"stack/compose.yaml", "stack/nginx.conf"}.issubset(names)
    if has_stack != (meta["component"] == "platform") or (
            meta["component"] == "web" and any(x.startswith("stack/") for x in names)):
        raise DeploymentError("Only platform releases may carry the complete stack configuration.")
    if digest(destination / "image.tar.gz") != meta["archive_sha256"]:
        raise DeploymentError("Image archive checksum mismatch.")
    return meta


@contextlib.contextmanager
def deployment_lock(root, timeout=600):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "deploy.lock").open("a") as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise DeploymentError("Another PDF Master deployment still holds the lock.")
                time.sleep(1)
        yield


class Deployer:
    def __init__(self, root, runner=command):
        self.root = root.resolve()
        self.run = runner

    def preflight(self):
        self.settings = environment(self.root)
        version = self.run(["docker", "compose", "version", "--short"]).lstrip("v").split(".")
        if tuple(int(x) for x in version[:2]) < (2, 24):
            raise DeploymentError("Docker Compose 2.24 or newer is required.")
        self.architecture = self.run(["docker", "info", "--format", "{{.Architecture}}"])
        self.architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(self.architecture, self.architecture)
        marker = self.root / ".owner"
        if not marker.exists():
            containers = self.run(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=pdfmaster"])
            volumes = self.run(["docker", "volume", "ls", "-q", "--filter", "label=com.docker.compose.project=pdfmaster"])
            if containers or volumes:
                raise DeploymentError("An unmanaged pdfmaster project already exists; inspect it before adoption.")
            marker.write_text("pdfmaster-deploy-v1\n")
        elif marker.read_text() != "pdfmaster-deploy-v1\n":
            raise DeploymentError("Unexpected deployment ownership marker.")
        return self.settings

    def compose(self, pair, *args, output_stream=None):
        platform = pair["platform"]
        config = self.root / "releases" / "platform" / platform["release_id"] / "stack" / "compose.yaml"
        env = dict(os.environ)
        # Avoid caller COMPOSE_* overrides and never print the rendered config.
        for key in list(env):
            if key.startswith("COMPOSE_"):
                del env[key]
        env.update(self.settings)
        env.update(PLATFORM_IMAGE=platform["image"], WEB_IMAGE=pair["web"]["image"],
                   PDFMASTER_ENV_FILE=str(self.root / ".env"))
        compose = ["docker", "compose", "--project-name", PROJECT,
                   "--env-file", str(self.root / ".env"), "-f", str(config)]
        override = self.root / "compose.override.yaml"
        if override.exists():
            if override.is_symlink() or not override.is_file():
                raise DeploymentError("Invalid server-owned Compose override.")
            compose += ["-f", str(override)]
        return self.run(compose + list(args), env=env, output_stream=output_stream)

    def activate(self, pair, backup=True):
        self.compose(pair, "config", "--quiet")
        self.compose(pair, "up", "-d", "--wait", "--wait-timeout", "120", "db", "redis")
        if backup:
            directory = self.root / "backups"
            directory.mkdir(exist_ok=True, mode=0o700)
            path = directory / f"before-{time.time_ns()}.dump"
            with path.open("xb") as stream:
                os.chmod(path, 0o600)
                self.compose(pair, "exec", "-T", "db", "pg_dump", "-U", "pdfmaster",
                             "-d", "pdfmaster", "-Fc", output_stream=stream)
        self.compose(pair, "run", "--rm", "--no-deps", "init")
        self.start_services(pair)

    def start_services(self, pair):
        services = SERVICES + (["bot"] if self.settings.get("COMPOSE_PROFILES") == "bot" else [])
        self.compose(pair, "up", "-d", "--wait", "--wait-timeout", "180", *services)
        if "bot" not in services:
            # Explicitly enable the profile for discovery; an unconfigured bot
            # is absent from the default Compose model.
            if self.compose(pair, "--profile", "bot", "ps", "-q", "bot"):
                self.compose(pair, "--profile", "bot", "stop", "bot")
        # Nginx resolves upstream addresses on startup. Recreate the gateway
        # after application replacements so it cannot retain an old container IP.
        self.compose(pair, "up", "-d", "--no-deps", "--force-recreate", "--wait",
                     "--wait-timeout", "120", "gateway")
        # Exercise routes through the gateway, not just container liveness.
        self.compose(pair, "exec", "-T", "gateway", "wget", "-q", "-O", "/dev/null",
                     "http://127.0.0.1:8080/api/v1/health")
        self.compose(pair, "exec", "-T", "gateway", "wget", "-q", "-O", "/dev/null",
                     "http://127.0.0.1:8080/en/app")

    def restore(self, pair):
        # Restore matching staff assets; never run reverse database migrations.
        self.compose(pair, "run", "--rm", "--no-deps", "init",
                     "python", "manage.py", "collectstatic", "--noinput")
        self.start_services(pair)

    def deploy(self, bundle):
        self.preflight()
        with tempfile.TemporaryDirectory(prefix="release-", dir=self.root) as temp:
            staging = Path(temp)
            meta = unpack(bundle, staging)
            if meta["architecture"] != self.architecture:
                raise DeploymentError("Image/server architecture mismatch; set DEPLOY_PLATFORM in both repositories.")
            state_path = self.root / "state.json"
            state = read_json(state_path, {"active": {}, "pending": {}, "runs": {}})
            component = meta["component"]
            # A slow older build must never supersede a newer release.
            if [meta["run_id"], meta["run_attempt"]] < state["runs"].get(component, [0, 0]):
                return {"status": "ignored_stale_release", "component": component}
            old = state.get("active", {})
            if old.get(component, {}).get("release_id") == meta["release_id"]:
                return {"status": "already_deployed", "component": component, "commit": meta["commit"]}
            destination = self.root / "releases" / component / meta["release_id"]
            existing = read_json(destination / "release.json")
            if existing and existing["image_id"] != meta["image_id"]:
                raise DeploymentError("This commit already has a different immutable image. Create a new commit.")
            with (staging / "image.tar.gz").open("rb") as stream:
                self.run(["docker", "load"], input_stream=stream)
            identity = self.run(["docker", "image", "inspect", "--format", "{{.Id}}", meta["image"]])
            if identity != meta["image_id"]:
                raise DeploymentError("Loaded image identity mismatch.")
            if not existing:
                destination.parent.mkdir(parents=True, exist_ok=True)
                (staging / "image.tar.gz").unlink()
                shutil.move(str(staging), destination)
                # Nginx's unprivileged uid must read this non-secret config.
                if component == "platform":
                    os.chmod(destination / "stack" / "nginx.conf", 0o644)
            state["pending"][component] = meta
            state["runs"][component] = [meta["run_id"], meta["run_attempt"]]
            write_json(state_path, state)
            pair = {**old, **state["pending"]}
            if set(pair) != {"platform", "web"}:
                return {"status": "staged_waiting_for_other_component", "component": component}
            if pair["platform"]["contract_sha256"] != pair["web"]["contract_sha256"]:
                return {"status": "staged_waiting_for_matching_api_contract", "component": component}
            try:
                self.activate(pair)
            except Exception:
                if old:
                    try:
                        self.restore(old)
                    except Exception:
                        raise DeploymentError("Deployment and image rollback failed. Inspect server logs and backups.") from None
                    state["pending"] = {}
                    write_json(state_path, state)
                raise DeploymentError("Release failed health/migration checks; previous images restored when available. Database migrations were not reversed.") from None
            state["previous"] = old
            state["active"] = pair
            state["pending"] = {}
            write_json(state_path, state)
            return {"status": "deployed", "commits": {key: value["commit"] for key, value in pair.items()}}

    def rollback(self):
        self.preflight()
        path = self.root / "state.json"
        state = read_json(path, {})
        previous = state.get("previous")
        if not previous:
            raise DeploymentError("No previous healthy release is recorded.")
        self.restore(previous)
        state["active"], state["previous"] = previous, state["active"]
        state["pending"] = {}
        write_json(path, state)
        return {"status": "rolled_back", "database": "unchanged"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("deploy", "rollback"))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--root", type=Path, default=Path.home() / "pdf-master")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        with deployment_lock(args.root):
            deployer = Deployer(args.root)
            if args.action == "deploy":
                if args.bundle is None:
                    raise DeploymentError("--bundle is required.")
                result = deployer.deploy(args.bundle)
            else:
                result = deployer.rollback()
        print(json.dumps(result))
    except (DeploymentError, OSError, ValueError, tarfile.TarError, subprocess.TimeoutExpired) as exc:
        # Unexpected parse/OS messages can expose paths; only approved messages
        # leave the host, never raw environment or subprocess stderr.
        print(str(exc) if isinstance(exc, DeploymentError) else "Deployment failed; inspect the server locally.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
