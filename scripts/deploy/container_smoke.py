#!/usr/bin/env python3
"""Boot this repository's real production stack in an ephemeral CI project."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

parser=argparse.ArgumentParser()
parser.add_argument('component',choices=('platform','web'))
parser.add_argument('image')
args=parser.parse_args()
repo=Path(__file__).resolve().parents[2]
name='pdfmaster-ci-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']

def run(command,**kwargs):return subprocess.run(command,check=True,**kwargs)

with tempfile.TemporaryDirectory() as temp:
    staging=Path(temp)
    run(['python3',str(repo/'scripts/deploy/init_environment.py'),'--component',args.component,'--root',str(staging)])
    env={**os.environ,'PDFMASTER_IMAGE':args.image,'PDFMASTER_ENV_FILE':str(staging/'.env'),
         'PDFMASTER_HTTP_PORT':'0'}
    compose=['docker','compose','-p',name,'--env-file',str(staging/'.env'),
             '-f',str(repo/'infra/production/compose.yaml')]
    try:
        run(compose+['config','--quiet'],env=env)
        if args.component=='platform':
            run(compose+['up','-d','--wait','--wait-timeout','120','db','redis'],env=env)
            run(compose+['run','--rm','--no-deps','init'],env=env)
            services=['api','worker','batches','cleanup','bot','gateway']
        else:
            services=['web','gateway']
        run(compose+['up','-d','--wait','--wait-timeout','180',*services],env=env)
        paths=['/en/app'] if args.component=='web' else ['/api/v1/health','/api/v1/plans','/ops/login','/static/ops/main.css']
        for path in paths:
            run(compose+['exec','-T','gateway','wget','-q','-O','/dev/null','http://127.0.0.1:8080'+path],env=env)
        if args.component=='platform':
            code="""import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.conf import settings
assert not settings.DEBUG and not settings.DEVELOPMENT_LOGIN_ENABLED and not settings.LOCAL_SYNC_JOBS
print('Production settings keep development features disabled.')
"""
            run(compose+['exec','-T','api','python','-c',code],env=env)
        print('Isolated '+args.component+' production stack and gateway routes verified.')
    finally:
        # Only the uniquely named ephemeral CI project may have volumes removed.
        subprocess.run(compose+['down','--volumes'],env=env,stdout=subprocess.DEVNULL)
print('Container smoke check passed.')
