"""Read-only server inventory: never print container environments or credentials."""
import json
from pathlib import Path
import subprocess

def output(args):
    result=subprocess.run(args,text=True,capture_output=True,timeout=30)
    return result.stdout.strip() if result.returncode==0 else 'unavailable'
def routes(args):
    try:
        value=json.loads(output(args))
    except (ValueError,TypeError):
        return 'No readable Caddyfile at the standard path'
    def walk(node):
        if isinstance(node,list):return [walk(x) for x in node]
        if not isinstance(node,dict):return node
        return {k:walk(v) for k,v in node.items() if k in {
            'apps','http','servers','routes','handle','match','host','path','handler',
            'upstreams','dial','listen','terminal','@id','subroute','tls_connection_policies'
        } or (isinstance(v,dict) and 'routes' in v)}
    return json.dumps(walk(value))
print('ARCHITECTURE' ,output(['uname','-m']))
print('ACCOUNT',output(['id','-un']))
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
            'restarts':c['RestartCount'],'oom_killed':c['State'].get('OOMKilled'),
            'ports':c['NetworkSettings']['Ports'],'networks':list(c['NetworkSettings']['Networks']),
            'mounts':[{'source':m['Source'],'target':m['Destination']} for m in c['Mounts']]}))
        if (c['Config']['Labels'].get('com.docker.compose.project') == 'pdfmaster-platform'
                and c['Config']['Labels'].get('com.docker.compose.service') == 'cleanup'):
            stats = {}
            for filename in ('memory.events', 'memory.current', 'memory.peak', 'memory.max'):
                value = output(['docker', 'exec', c['Id'], 'cat', '/sys/fs/cgroup/' + filename])
                stats[filename] = value if all(part.isdigit() or part.replace('_', '').isalpha()
                    for part in value.split()) else 'unavailable'
            print('PDFMASTER_CLEANUP_MEMORY', json.dumps(stats))
        if 'caddy' in c['Config']['Image'].lower():
            print('CADDY_ROUTES',routes(['docker','exec',c['Id'],'caddy','adapt','--config','/etc/caddy/Caddyfile','--pretty']))
for path in ('/etc/caddy/Caddyfile',str(Path.home()/'pdf-master/state.json')):
    p=Path(path)
    if p.is_file():
        if path.endswith('state.json'):print('EXISTING_PDFMASTER_STATE',p.read_text())
        else:print('HOST_CADDY_ROUTES',routes(['caddy','adapt','--config',path,'--pretty']))
print('PDFMASTER_PATH_EXISTS',(Path.home()/'pdf-master').exists())
