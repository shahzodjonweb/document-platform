"""Release transaction tests use real archives/files and a bounded fake Docker boundary."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

DIRECTORY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("deployment_server", DIRECTORY / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

class Docker:
    def __init__(self):
        self.calls = []
        self.images = {}
        self.fail_health = False
        self.project_exists = False
    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[:3] == ["docker", "compose", "version"]: return "2.39.0"
        if args[:2] == ["docker", "info"]: return "x86_64"
        if args[:2] == ["docker", "ps"]: return "other-container" if self.project_exists else ""
        if args[:3] == ["docker", "volume", "ls"]: return ""
        if args[:3] == ["docker", "image", "inspect"]: return self.images[args[-1]]
        if "pg_dump" in args:
            kwargs["output_stream"].write(b"PGDMP test backup")
            return ""
        if self.fail_health and "up" in args and "gateway" in args:
            self.fail_health = False
            raise server.DeploymentError("Synthetic failed health check")
        return ""

class Releases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "pdf-master"
        self.root.mkdir()
        self.env = self.root / ".env"
        self.env.write_text("\n".join([
            "SECRET_KEY=" + "s"*48, "POSTGRES_PASSWORD=" + "p"*40,
            "FILE_SECRET_KEY=" + "f"*44, "INTEGRATION_ENCRYPTION_KEY=" + "i"*44,
            "ALLOWED_HOSTS=pdf.test,127.0.0.1,localhost,api",
            "CSRF_TRUSTED_ORIGINS=https://pdf.test",
            "DEBUG=0", "DEVELOPMENT_LOGIN_ENABLED=0", "COMMERCE_SANDBOX_ENABLED=0",
        ]) + "\n")
        self.env.chmod(0o600)
        self.docker = Docker()
        self.deployer = server.Deployer(self.root, self.docker)
    def tearDown(self): self.temp.cleanup()
    def bundle(self, component, run, *, contract="c"*64, architecture="amd64", attempt=1, corrupt=False):
        sha = hashlib.sha1((component + str(run)).encode()).hexdigest()
        release_id = f"{sha}-{run}-{attempt}"
        image_bytes = b"opaque docker stream"
        meta = {"protocol":1, "component":component, "commit":sha, "release_id":release_id,
                "run_id":run, "run_attempt":attempt, "image":f"pdfmaster-{component}:{release_id}",
                "image_id":"sha256:"+hashlib.sha256(release_id.encode()).hexdigest(),
                "architecture":architecture, "contract_sha256":contract,
                "archive_sha256":hashlib.sha256(image_bytes if not corrupt else b"wrong").hexdigest()}
        self.docker.images[meta["image"]] = meta["image_id"]
        members = {"release.json": json.dumps(meta).encode(), "image.tar.gz": image_bytes}
        if component == "platform":
            members.update({"stack/compose.yaml":b"name: pdfmaster\n", "stack/nginx.conf":b"server {}"})
        target = Path(self.temp.name) / (release_id + ".tgz")
        with tarfile.open(target, "w:gz") as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(name); info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return target, meta
    def deploy(self, component, run, **kwargs):
        bundle, meta = self.bundle(component, run, **kwargs)
        return self.deployer.deploy(bundle), meta
    def state(self): return json.loads((self.root/"state.json").read_text())

    def test_first_component_stages_then_matching_pair_activates(self):
        result, platform = self.deploy("platform", 10)
        self.assertEqual(result["status"], "staged_waiting_for_other_component")
        self.assertFalse(any("up" in x for x in self.docker.calls))
        result, web = self.deploy("web", 11)
        self.assertEqual(result["status"], "deployed")
        self.assertEqual(self.state()["active"], {"platform":platform,"web":web})
        backups = list((self.root/"backups").glob("*.dump"))
        self.assertEqual(backups[0].read_bytes(), b"PGDMP test backup")
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        commands = self.docker.calls
        self.assertFalse(any("down" in x or "prune" in x for x in commands))
        self.assertTrue(all(x[x.index("--project-name")+1]=="pdfmaster"
                            for x in commands if "--project-name" in x))

    def test_gateway_restarts_after_apps_and_rollback_checks_routes(self):
        self.deploy("platform",10); self.deploy("web",11)
        self.docker.calls.clear()
        self.deploy("web",12)
        application = next(i for i,c in enumerate(self.docker.calls) if "up" in c and "api" in c)
        gateway = next(i for i,c in enumerate(self.docker.calls) if "up" in c and "gateway" in c)
        self.assertLess(application, gateway)
        self.assertIn("--force-recreate", self.docker.calls[gateway])
        self.docker.calls.clear()
        self.deployer.rollback()
        self.assertTrue(any("http://127.0.0.1:8080/en/app" in c for c in self.docker.calls))

    def test_web_may_arrive_first(self):
        self.assertEqual(self.deploy("web", 2)[0]["status"],"staged_waiting_for_other_component")
        self.assertEqual(self.deploy("platform", 3)[0]["status"],"deployed")

    def test_contract_mismatch_keeps_healthy_stack_until_matching_release(self):
        self.deploy("platform",10);self.deploy("web",11)
        active=self.state()["active"]
        self.docker.calls.clear()
        self.assertEqual(self.deploy("platform",12,contract="d"*64)[0]["status"],"staged_waiting_for_matching_api_contract")
        self.assertEqual(self.state()["active"],active)
        self.assertFalse(any("up" in x for x in self.docker.calls))
        self.assertEqual(self.deploy("web",13,contract="d"*64)[0]["status"],"deployed")

    def test_health_failure_restores_previous_images_without_database_rollback(self):
        self.deploy("platform",10);self.deploy("web",11)
        active=self.state()["active"]
        self.docker.fail_health=True
        with self.assertRaisesRegex(server.DeploymentError,"previous images restored"):
            self.deploy("web",12)
        self.assertEqual(self.state()["active"],active)
        self.assertEqual(self.state()["pending"],{})
        self.assertFalse(any("down" in x or "pg_restore" in x for x in self.docker.calls))

    def test_manual_rollback_restores_recorded_pair(self):
        self.deploy("platform",10);self.deploy("web",11)
        previous=self.state()["active"]
        self.deploy("web",12)
        self.assertEqual(self.deployer.rollback()["status"],"rolled_back")
        self.assertEqual(self.state()["active"],previous)

    def test_slow_old_run_cannot_override_newer_run(self):
        self.deploy("platform",10);self.deploy("web",11);self.deploy("web",13)
        active=self.state()["active"]
        self.assertEqual(self.deploy("web",12)[0]["status"],"ignored_stale_release")
        self.assertEqual(self.state()["active"],active)

    def test_repeated_release_is_idempotent(self):
        self.deploy("platform",10)
        bundle,meta=self.bundle("web",11)
        self.deployer.deploy(bundle)
        self.docker.calls.clear()
        self.assertEqual(self.deployer.deploy(bundle)["status"],"already_deployed")
        self.assertFalse(any("up" in x or "load" in x for x in self.docker.calls))

    def test_archive_tampering_rejected_before_docker_load(self):
        with self.assertRaisesRegex(server.DeploymentError,"checksum"):
            self.deploy("web",2,corrupt=True)
        self.assertFalse(any("load" in x for x in self.docker.calls))

    def test_architecture_mismatch_rejected(self):
        with self.assertRaisesRegex(server.DeploymentError,"architecture"):
            self.deploy("web",2,architecture="arm64")
        self.assertFalse(any("load" in x for x in self.docker.calls))

    def test_cannot_adopt_other_project(self):
        self.docker.project_exists=True
        with self.assertRaisesRegex(server.DeploymentError,"unmanaged"):
            self.deploy("web",2)
        self.assertFalse(any("load" in x for x in self.docker.calls))

    def test_development_flags_and_readable_secret_file_rejected(self):
        self.env.chmod(0o644)
        with self.assertRaisesRegex(server.DeploymentError,"600"):
            self.deploy("web",2)
        self.env.chmod(0o600)
        self.env.write_text(self.env.read_text().replace("DEBUG=0","DEBUG=1"))
        with self.assertRaisesRegex(server.DeploymentError,"Development"):
            self.deploy("web",2)

    def test_path_traversal_symlinks_and_duplicate_members_are_rejected(self):
        for case in ("../escape","symlink","duplicate"):
            with self.subTest(case=case):
                target=Path(self.temp.name)/"bad.tgz"
                with tarfile.open(target,"w:gz") as archive:
                    item=tarfile.TarInfo("../escape" if case=="../escape" else "release.json")
                    if case=="symlink":
                        item.type=tarfile.SYMTYPE;item.linkname="/etc/passwd"
                    archive.addfile(item)
                    if case=="duplicate":archive.addfile(item)
                with tempfile.TemporaryDirectory() as destination:
                    with self.assertRaises(server.DeploymentError):
                        server.unpack(target,Path(destination))

    def test_missing_variables_are_explicitly_reported_without_values(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/"out";summary=Path(temp)/"summary"
            env={key:value for key,value in os.environ.items() if not key.startswith("DEPLOY_")}
            env.update(GITHUB_OUTPUT=str(output),GITHUB_STEP_SUMMARY=str(summary))
            result=subprocess.run([sys.executable,str(DIRECTORY/"check_configuration.py")],env=env,capture_output=True,check=True)
            self.assertIn("configured=false",output.read_text())
            for name in ("DEPLOY_HOST","DEPLOY_USER","DEPLOY_SSH_KEY","DEPLOY_KNOWN_HOSTS"):
                self.assertIn(name,summary.read_text())
            self.assertIn("no server connection was attempted",summary.read_text())

    def test_cross_repository_lock_excludes_second_deployer(self):
        with server.deployment_lock(self.root):
            with self.assertRaisesRegex(server.DeploymentError, "holds the lock"):
                with server.deployment_lock(self.root, timeout=0):
                    self.fail("Second deployer acquired an active lock")
        with server.deployment_lock(self.root, timeout=0):
            pass

    def test_loaded_image_identity_must_match_manifest(self):
        bundle, meta = self.bundle("platform", 10)
        self.docker.images[meta["image"]] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(server.DeploymentError, "identity mismatch"):
            self.deployer.deploy(bundle)
        self.assertFalse((self.root / "state.json").exists())

    def test_ready_configuration_check_never_echoes_values(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/"out";summary=Path(temp)/"summary"
            env={**os.environ,"GITHUB_OUTPUT":str(output),"GITHUB_STEP_SUMMARY":str(summary)}
            for name in ("DEPLOY_HOST","DEPLOY_USER","DEPLOY_SSH_KEY","DEPLOY_KNOWN_HOSTS"):
                env[name]="sentinel-sensitive-value"
            result=subprocess.run([sys.executable,str(DIRECTORY/"check_configuration.py")],env=env,capture_output=True,check=True)
            self.assertIn("configured=true",output.read_text())
            self.assertNotIn("sentinel-sensitive-value",summary.read_text()+result.stdout.decode()+result.stderr.decode())
