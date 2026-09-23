"""Read-only server inventory: never print container environments or credentials."""
import json
from pathlib import Path
import subprocess

def output(args):
    result=subprocess.run(args,text=True,capture_output=True,timeout=30)
    return result.stdout.strip() if result.returncode==0 else 'unavailable'
print('ARCHITECTURE',output(['uname','-m']))
print('COMPOSE',output(['docker','compose','version','--short']))
print('MEMORY',output(['free','-m']))
print('DISK',output(['df','-h','/']))
print('LISTENERS',output(['ss','-ltnp']))
ids=output(['docker','ps','-aq']).splitlines()
if ids and ids!=['unavailable']:
    containers=json.loads(output(['docker','inspect',*ids]))
    for c in containers:
        print('CONTAINER',json.dumps({'id':c['Id'],'name':c['Name'],'image':c['Config']['Image'],
            'project':c['Config']['Labels'].get('com.docker.compose.project'),
            'config_files':c['Config']['Labels'].get('com.docker.compose.project.config_files'),
            'status':c['State']['Status'],'started':c['State'].get('StartedAt'),
            'ports':c['NetworkSettings']['Ports'],'networks':list(c['NetworkSettings']['Networks']),
            'mounts':[{'source':m['Source'],'target':m['Destination']} for m in c['Mounts']]}))
        if 'caddy' in c['Config']['Image'].lower():
            print('CADDY_ROUTES',output(['docker','exec',c['Id'],'caddy','adapt','--config','/etc/caddy/Caddyfile','--pretty']))
for path in ('/etc/caddy/Caddyfile','/root/pdf-master/state.json'):
    p=Path(path)
    if p.is_file():
        if path.endswith('state.json'):print('EXISTING_PDFMASTER_STATE',p.read_text())
        else:print('HOST_CADDY_ROUTES',output(['caddy','adapt','--config',path,'--pretty']))
print('PDFMASTER_PATH_EXISTS',Path('/root/pdf-master').exists())
