"""Bounded source extraction; stdout contains private text only for the requesting service."""
import json
import os
import subprocess
import sys
from apps.core.errors import DomainError

def extract_pages(path):
    program='''import json,sys,resource
resource.setrlimit(resource.RLIMIT_CPU,(20,20))
resource.setrlimit(resource.RLIMIT_FSIZE,(2097152,2097152))
if sys.platform != 'darwin': resource.setrlimit(resource.RLIMIT_AS,(1073741824,1073741824))
from pypdf import PdfReader
r=PdfReader(sys.argv[1]); out=[]
for i,p in enumerate(r.pages):
 t=p.extract_text() or ''
 if len(t)>12000: t=t[:12000]
 out.append([i+1,t])
print(json.dumps(out))
'''
    try:
        result=subprocess.run([sys.executable,'-c',program,str(path)],capture_output=True,timeout=30,env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','TMPDIR','SYSTEMROOT')},check=True)
        if len(result.stdout)>2_000_000:raise ValueError()
        return json.loads(result.stdout)
    except Exception:raise DomainError('source_extraction_failed') from None
