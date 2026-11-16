"""Bounded source extraction; stdout contains private text only for the requesting service."""
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
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

# What one CV source file's reading prints, at most; the program that reads
# it; and how long past its own budget it is given before it is killed.
CV_REPORT_LIMIT=2_000_000
CV_READER=Path(__file__).resolve().parent/'cv'/'reader.py'
CV_GRACE_SECONDS=5

def read_cv(path,kind,*,ocr_pages,seconds):
    """One CV source file read in its own bounded child (cv/reader.py): {'pages','names','ocr_pages','ocr_skipped'}.

    `kind` is 'pdf', 'docx' or 'image'. A PDF is read column by column, a page
    without a text layer and an image by OCR, at most `ocr_pages` of them;
    `seconds` is the wall-clock budget of the whole child, after which it and
    any tesseract it started are killed. Its text is the customer's, so it is
    never logged; a failure of any kind is 'source_extraction_failed', with
    nothing of the file in it.
    """
    from processors.advanced import ASSETS,tesseract_runtime
    runtime=tesseract_runtime()
    executable=runtime['executable'] if runtime['available'] else ''
    # Parsers never inherit database, Telegram, signing or provider credentials.
    environment={key:os.environ[key] for key in ('PATH','LANG','LC_ALL','TMPDIR','SYSTEMROOT') if key in os.environ}
    environment.update(PYTHONDONTWRITEBYTECODE='1',OMP_THREAD_LIMIT='1',OMP_NUM_THREADS='1',MALLOC_ARENA_MAX='2')
    seconds=max(5,int(seconds))
    try:
        with tempfile.TemporaryFile() as report:
            process=subprocess.Popen([sys.executable,'-I',str(CV_READER),kind,str(Path(path).absolute()),executable or '',
                                      str(ASSETS/'tessdata'),str(max(0,int(ocr_pages))),str(seconds)],
                                     stdin=subprocess.DEVNULL,stdout=report,stderr=subprocess.DEVNULL,
                                     start_new_session=True,env=environment,cwd=tempfile.gettempdir())
            try:
                process.wait(timeout=seconds+CV_GRACE_SECONDS)
            finally:
                # The child's tesseract is in its group: nothing outlives the budget.
                try:os.killpg(process.pid,signal.SIGKILL)
                except (ProcessLookupError,PermissionError):pass
                process.wait()
            if process.returncode!=0 or report.tell()>CV_REPORT_LIMIT:raise ValueError()
            report.seek(0)
            result=json.loads(report.read(CV_REPORT_LIMIT))
        if not isinstance(result,dict) or not isinstance(result.get('pages'),list):raise ValueError()
        return result
    except Exception:raise DomainError('source_extraction_failed') from None

# A category's Word and text sources (processors/source_reader.py): the kinds
# it reads, the most its report may hold (3,000,000 characters of Cyrillic
# with JSON's escapes), and how long past its budget it is given before it
# is killed. PDFs are read by extract_pages, as they always were.
SOURCE_KINDS=('docx','doc','text')
SOURCE_REPORT_LIMIT=16_000_000
SOURCE_READER=Path(__file__).resolve().parents[2]/'processors'/'source_reader.py'
SOURCE_GRACE_SECONDS=5

def read_source(path,kind,*,seconds=30):
    """One Word or text source of a category read in its own bounded child: [(part, text)], parts numbered from 1.

    `kind` is the upload's: 'docx', 'doc' (old binary Word, read by antiword)
    or 'text'. The parts are processors/source_text.pages of the file's text,
    so a `.doc` or `.txt` has as many as the page count its upload stored.
    The child has the boundary of read_cv: `-I`, argv only, an environment
    of its own, output to a temporary file under a size limit, its own
    session killed whole after `seconds`. Its text is the customer's and is
    never logged; any failure is 'source_extraction_failed' with nothing of
    the file in it. A file longer than any source may be is 'generation_limit'
    (the child stops reading and says so rather than cutting it), and an old
    Word file where antiword is missing 'conversion_preflight_unavailable', as
    its upload would have been.
    """
    if kind not in SOURCE_KINDS:raise DomainError('source_extraction_failed')
    executable=''
    if kind=='doc':
        from processors.engine import antiword_runtime
        executable=antiword_runtime()
        if not executable:raise DomainError('conversion_preflight_unavailable')
    # Parsers never inherit database, Telegram, signing or provider credentials.
    environment={key:os.environ[key] for key in ('PATH','LANG','LC_ALL','TMPDIR','SYSTEMROOT') if key in os.environ}
    environment.update(PYTHONDONTWRITEBYTECODE='1',MALLOC_ARENA_MAX='2')
    seconds=max(5,int(seconds))
    try:
        with tempfile.TemporaryFile() as report:
            process=subprocess.Popen([sys.executable,'-I',str(SOURCE_READER),kind,str(Path(path).absolute()),executable,str(seconds)],
                                     stdin=subprocess.DEVNULL,stdout=report,stderr=subprocess.DEVNULL,
                                     start_new_session=True,env=environment,cwd=tempfile.gettempdir())
            try:
                process.wait(timeout=seconds+SOURCE_GRACE_SECONDS)
            finally:
                # antiword is in the child's group: nothing outlives the budget.
                try:os.killpg(process.pid,signal.SIGKILL)
                except (ProcessLookupError,PermissionError):pass
                process.wait()
            if process.returncode!=0 or report.tell()>SOURCE_REPORT_LIMIT:raise ValueError()
            report.seek(0)
            result=json.loads(report.read(SOURCE_REPORT_LIMIT))
        parts=result['parts'] if isinstance(result,dict) else None
        if not isinstance(parts,list) or not all(isinstance(part,str) for part in parts) or not isinstance(result.get('truncated'),bool):raise ValueError()
        truncated=result['truncated']
    except Exception:raise DomainError('source_extraction_failed') from None
    if truncated:raise DomainError('generation_limit')
    return list(enumerate(parts,1))
