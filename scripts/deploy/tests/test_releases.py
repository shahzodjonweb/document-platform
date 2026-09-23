"""Release transactions operate on real archives and a bounded fake Docker boundary."""
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
spec = importlib.util.spec_from_file_location('deployment_server', DIRECTORY / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

class Docker:
    def __init__(self):
        self.calls=[]; self.images={}; self.fail_health=False; self.project_exists=False
    def __call__(self,args,**kwargs):
        self.calls.append(args)
        if args[:3]==['docker','compose','version']:return '2.39.0'
        if args[:2]==['docker','info']:return 'x86_64'
        if args[:2]==['docker','ps']:return 'unmanaged-container' if self.project_exists else ''
        if args[:3]==['docker','volume','ls']:return ''
        if args[:3]==['docker','image','inspect']:return self.images[args[-1]]
        if 'pg_dump' in args:
            kwargs['output_stream'].write(b'PGDMP test backup');return ''
        if self.fail_health and 'up' in args and 'gateway' in args:
            self.fail_health=False
            raise server.DeploymentError('Synthetic failed health check')
        return ''

class Releases(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/'pdf-master'
        self.docker=Docker()
        for component in ('platform','web'):
            root=self.root/component;root.mkdir(parents=True)
            domain='pdfmaster-admin.orderdesk.live' if component=='platform' else 'pdfmaster.orderdesk.live'
            env=root/'.env'
            env.write_text('\n'.join([
                'PUBLIC_DOMAIN='+domain, 'SECRET_KEY='+'s'*48, 'POSTGRES_PASSWORD='+'p'*40,
                'FILE_SECRET_KEY='+'f'*44, 'INTEGRATION_ENCRYPTION_KEY='+'i'*44,
                'ALLOWED_HOSTS=pdfmaster-admin.orderdesk.live,127.0.0.1,localhost,api',
                'CSRF_TRUSTED_ORIGINS=https://pdfmaster.orderdesk.live',
                'DEBUG=0','DEVELOPMENT_LOGIN_ENABLED=0','COMMERCE_SANDBOX_ENABLED=0',
            ])+'\n');env.chmod(0o600)
    def tearDown(self):self.temp.cleanup()
    def deployer(self,component):return server.Deployer(self.root/component,component,self.docker)
    def bundle(self,component,run,*,contract='c'*64,architecture='amd64',attempt=1,corrupt=False):
        sha=hashlib.sha1((component+str(run)).encode()).hexdigest()
        release_id=f'{sha}-{run}-{attempt}'
        image_bytes=b'opaque docker stream'
        meta={'protocol':2,'component':component,'commit':sha,'release_id':release_id,
              'run_id':run,'run_attempt':attempt,'image':f'pdfmaster-{component}:{release_id}',
              'image_id':'sha256:'+hashlib.sha256(release_id.encode()).hexdigest(),
              'architecture':architecture,'contract_sha256':contract,
              'archive_sha256':hashlib.sha256(image_bytes if not corrupt else b'wrong').hexdigest()}
        self.docker.images[meta['image']]=meta['image_id']
        members={'release.json':json.dumps(meta).encode(),'image.tar.gz':image_bytes,
                 'stack/compose.yaml':('name: pdfmaster-'+component+'\n').encode(),'stack/nginx.conf':b'server {}'}
        target=Path(self.temp.name)/(release_id+'.tgz')
        with tarfile.open(target,'w:gz') as archive:
            for name,data in members.items():
                info=tarfile.TarInfo(name);info.size=len(data);archive.addfile(info,io.BytesIO(data))
        return target,meta
    def deploy(self,component,run,**kwargs):
        bundle,meta=self.bundle(component,run,**kwargs)
        return self.deployer(component).deploy(bundle),meta
    def state(self,component):return json.loads((self.root/component/'state.json').read_text())
    def assert_only_project(self,component):
        for call in self.docker.calls:
            if '--project-name' in call:
                self.assertEqual(call[call.index('--project-name')+1],'pdfmaster-'+component)
                self.assertIn(str((self.root/component/'.env').resolve()),call)
        self.assertFalse(any('down' in c or 'prune' in c or '--remove-orphans' in c for c in self.docker.calls))

    def test_platform_first_release_starts_independently_and_backs_up(self):
        result,meta=self.deploy('platform',10)
        self.assertEqual(result['status'],'deployed')
        self.assertEqual(self.state('platform')['active'],meta)
        self.assertFalse((self.root/'web/state.json').exists())
        backups=list((self.root/'platform/backups').glob('*.dump'))
        self.assertEqual(backups[0].read_bytes(),b'PGDMP test backup')
        self.assertEqual(backups[0].stat().st_mode&0o777,0o600)
        self.assert_only_project('platform')

    def test_web_first_release_needs_no_platform_or_database(self):
        result,meta=self.deploy('web',2)
        self.assertEqual(result['status'],'deployed')
        self.assertFalse((self.root/'platform/state.json').exists())
        self.assert_only_project('web')
        self.assertFalse(any(x in c for c in self.docker.calls for x in ('db','redis','pg_dump','init','api','bot','worker')))

    def test_web_update_never_reads_or_changes_platform_state(self):
        self.deploy('platform',10);self.deploy('web',11)
        state=(self.root/'platform/state.json').read_bytes()
        # Removing peer state proves it is not an input to web deployment.
        (self.root/'platform/state.json').unlink()
        self.docker.calls.clear()
        self.assertEqual(self.deploy('web',12,contract='d'*64)[0]['status'],'deployed')
        self.assert_only_project('web')
        self.assertFalse((self.root/'platform/state.json').exists())
        (self.root/'platform/state.json').write_bytes(state)

    def test_platform_update_leaves_web_release_untouched(self):
        self.deploy('platform',10);self.deploy('web',11)
        active=self.state('web')
        self.docker.calls.clear();self.deploy('platform',12)
        self.assertEqual(self.state('web'),active)
        self.assert_only_project('platform')

    def test_failed_web_release_restores_only_web_without_database_commands(self):
        self.deploy('platform',10);self.deploy('web',11)
        platform=self.state('platform');web=self.state('web')['active']
        self.docker.calls.clear();self.docker.fail_health=True
        with self.assertRaisesRegex(server.DeploymentError,'previous image restored'):
            self.deploy('web',12)
        self.assertEqual(self.state('platform'),platform)
        self.assertEqual(self.state('web')['active'],web)
        self.assertIsNone(self.state('web')['pending'])
        self.assert_only_project('web')
        self.assertFalse(any('pg_restore' in c or 'init' in c for c in self.docker.calls))

    def test_manual_rollback_affects_only_selected_project(self):
        self.deploy('platform',10);self.deploy('web',11)
        previous=self.state('platform')['active'];web=self.state('web')
        self.deploy('platform',12);self.docker.calls.clear()
        self.assertEqual(self.deployer('platform').rollback()['status'],'rolled_back')
        self.assertEqual(self.state('platform')['active'],previous)
        self.assertEqual(self.state('web'),web)
        self.assert_only_project('platform')

    def test_gateway_restarts_after_own_app_and_checks_routes(self):
        self.deploy('web',10)
        app=next(i for i,c in enumerate(self.docker.calls) if 'up' in c and 'web' in c)
        gateway=next(i for i,c in enumerate(self.docker.calls) if 'up' in c and 'gateway' in c)
        self.assertLess(app,gateway)
        self.assertIn('--force-recreate',self.docker.calls[gateway])
        self.assertTrue(any('http://127.0.0.1:8080/en/app' in c for c in self.docker.calls))

    def test_older_run_cannot_override_newer_release(self):
        self.deploy('web',13);active=self.state('web')['active']
        self.assertEqual(self.deploy('web',12)[0]['status'],'ignored_stale_release')
        self.assertEqual(self.state('web')['active'],active)

    def test_repeated_release_is_idempotent(self):
        bundle,meta=self.bundle('web',11)
        deployer=self.deployer('web');deployer.deploy(bundle);self.docker.calls.clear()
        self.assertEqual(deployer.deploy(bundle)['status'],'already_deployed')
        self.assertFalse(any('up' in c or 'load' in c for c in self.docker.calls))

    def test_bundle_cannot_be_deployed_to_the_other_component(self):
        bundle,_=self.bundle('platform',10)
        with self.assertRaisesRegex(server.DeploymentError,'different isolated project'):
            self.deployer('web').deploy(bundle)
        self.assertFalse(any('load' in c for c in self.docker.calls))

    def test_checksum_and_architecture_rejected_before_load(self):
        for kwargs in ({'corrupt':True},{'architecture':'arm64'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(server.DeploymentError):
                self.deploy('web',2,**kwargs)
        self.assertFalse(any('load' in c for c in self.docker.calls))

    def test_unmanaged_project_is_not_adopted(self):
        self.docker.project_exists=True
        with self.assertRaisesRegex(server.DeploymentError,'unmanaged'):self.deploy('web',2)
        self.assertFalse(any('load' in c for c in self.docker.calls))

    def test_environment_permissions_and_development_flags_rejected(self):
        env=self.root/'platform/.env';env.chmod(0o644)
        with self.assertRaisesRegex(server.DeploymentError,'600'):self.deploy('platform',2)
        env.chmod(0o600);env.write_text(env.read_text().replace('DEBUG=0','DEBUG=1'))
        with self.assertRaisesRegex(server.DeploymentError,'Development'):self.deploy('platform',2)

    def test_archive_traversal_links_duplicates_and_missing_stack_rejected(self):
        for case in ('../escape','symlink','duplicate','missing-stack'):
            with self.subTest(case=case):
                target=Path(self.temp.name)/'bad.tgz'
                with tarfile.open(target,'w:gz') as archive:
                    item=tarfile.TarInfo('../escape' if case=='../escape' else 'release.json')
                    if case=='symlink':item.type=tarfile.SYMTYPE;item.linkname='/etc/passwd'
                    archive.addfile(item)
                    if case=='duplicate':archive.addfile(item)
                with tempfile.TemporaryDirectory() as dest,self.assertRaises(server.DeploymentError):
                    server.unpack(target,Path(dest))

    def test_same_project_lock_serializes_but_other_project_is_independent(self):
        with server.deployment_lock(self.root/'web'):
            with self.assertRaisesRegex(server.DeploymentError,'holds the lock'):
                with server.deployment_lock(self.root/'web',timeout=0):pass
            with server.deployment_lock(self.root/'platform',timeout=0):pass

    def test_loaded_image_identity_must_match(self):
        bundle,meta=self.bundle('platform',10)
        self.docker.images[meta['image']]='sha256:'+'0'*64
        with self.assertRaisesRegex(server.DeploymentError,'identity mismatch'):
            self.deployer('platform').deploy(bundle)
        self.assertFalse((self.root/'platform/state.json').exists())

    def test_readiness_names_missing_settings_and_never_echoes_values(self):
        names=('DEPLOY_HOST','DEPLOY_USER','DEPLOY_SSH_KEY','DEPLOY_KNOWN_HOSTS')
        for ready in (False,True):
            with self.subTest(ready=ready),tempfile.TemporaryDirectory() as temp:
                output=Path(temp)/'out';summary=Path(temp)/'summary'
                env={k:v for k,v in os.environ.items() if not k.startswith('DEPLOY_')}
                env.update(GITHUB_OUTPUT=str(output),GITHUB_STEP_SUMMARY=str(summary))
                if ready:env.update({k:'sentinel-sensitive-value' for k in names})
                result=subprocess.run([sys.executable,str(DIRECTORY/'check_configuration.py')],env=env,capture_output=True,check=True)
                self.assertIn('configured='+str(ready).lower(),output.read_text())
                self.assertNotIn('sentinel-sensitive-value',summary.read_text()+result.stdout.decode()+result.stderr.decode())
                if not ready:
                    for name in names:self.assertIn(name,summary.read_text())
                    self.assertIn('no server connection was attempted',summary.read_text())

    def test_rejected_ssh_does_not_dump_a_broken_pipe_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            for name,code in [('ssh',255),('ssh-keygen',0)]:
                executable=folder/name
                executable.write_text('#!/bin/sh\nexit '+str(code)+'\n')
                executable.chmod(0o700)
            bundle=folder/'release.tar.gz';bundle.write_bytes(b'x'*1024*1024)
            env={**os.environ,'PATH':str(folder)+os.pathsep+os.environ['PATH'],
                 'DEPLOY_HOST':'server.example','DEPLOY_USER':'root',
                 'DEPLOY_SSH_KEY':'sentinel-private-value','DEPLOY_KNOWN_HOSTS':'sentinel-host-value',
                 'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'20','GITHUB_RUN_ATTEMPT':'1'}
            result=subprocess.run([sys.executable,str(DIRECTORY/'client.py'),'web','--bundle',str(bundle)],
                                  env=env,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('SSH connection closed before release delivery',result.stderr)
            self.assertNotIn('Traceback',result.stderr)
            self.assertNotIn('sentinel-private-value',result.stdout+result.stderr)
