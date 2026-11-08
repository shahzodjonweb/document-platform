"""PdfCraft's command line editor, started only from inside the processor child (processors/__main__.py).

It inherits the child's limits and stays in the child's process group, so the
sandbox's group kill on a timeout reaches it too: that is why it gets no session
of its own. It sees nothing of the worker's environment but PATH, with its home,
temp and XDG folders at the root it is given, and every file it reads or writes
is inside that root. Its report holds the document's words, so nothing of it
goes into an error, a log line or a job's metadata.
"""
from __future__ import annotations
import json
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

MANIFEST=Path(__file__).resolve().parent/'pdfcraft'/'manifest.json'
ISOLATION=('HOME','TMPDIR','XDG_CACHE_HOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_RUNTIME_DIR')
REPORT_LIMIT=2*1024*1024
SECONDS=30


class Failed(Exception):
    """A run that could not start, timed out or printed no report. It carries none of the report's words."""


@lru_cache(maxsize=1)
def version():
    """The release the image installs (scripts/fetch_pdfcraft.py), and the only one this code speaks to."""
    return json.loads(MANIFEST.read_text())['version']


def _environment(root):
    return {'PATH':os.environ.get('PATH',''),**dict.fromkeys(ISOLATION,str(root))}


@lru_cache(maxsize=4)
def _speaks(executable,root):
    try:
        probe=subprocess.run([executable,'--version'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,cwd=root,env=_environment(root),timeout=10,check=False)
    except (OSError,subprocess.SubprocessError):
        return False
    first=probe.stdout[:1024].decode('utf-8','replace').splitlines()[:1]
    return probe.returncode==0 and first==[f'pdfcraft-cli {version()}']


def binary(root):
    """The configured binary when it is the pinned release, else None. `root` is where its version is asked, under the same isolation as a run."""
    configured=os.environ.get('PDFMASTER_PDFCRAFT_BIN')
    if not configured:return None
    # Runs start inside the root, so a relative name must be fixed first.
    executable=Path(configured).resolve()
    if not executable.is_file() or not os.access(executable,os.X_OK):return None
    return str(executable) if _speaks(str(executable),str(root)) else None


def run(executable,steps,root,timeout=SECONDS):
    """One script; returns its report, whose `ok` says whether every step went through. Raises Failed when there is no report to read."""
    root=Path(root);script=root/'steps.json'
    script.write_text(json.dumps(steps,ensure_ascii=False))
    # The report goes to a file, never a pipe: a large one cannot stall the binary, and only REPORT_LIMIT of it is read.
    with tempfile.TemporaryFile(dir=root) as report:
        try:
            subprocess.run([executable,'run','--script',str(script),'--report','--root',str(root)],stdin=subprocess.DEVNULL,stdout=report,stderr=subprocess.DEVNULL,cwd=root,env=_environment(root),timeout=timeout,check=False)
        except (OSError,subprocess.SubprocessError):
            raise Failed() from None
        if report.tell()>REPORT_LIMIT:raise Failed()
        report.seek(0)
        try:answer=json.loads(report.read(REPORT_LIMIT))
        except (ValueError,UnicodeError):raise Failed() from None
    if not isinstance(answer,dict) or not isinstance(answer.get('steps'),list) or len(answer['steps'])!=len(steps):raise Failed()
    return answer


def result(report,index):
    """What one step of a run answered, or None when it did not go through."""
    step=report['steps'][index]
    if not isinstance(step,dict) or step.get('status')!='ok':return None
    value=step.get('result')
    value=value[0] if isinstance(value,list) and value else value
    return value if isinstance(value,dict) else None
