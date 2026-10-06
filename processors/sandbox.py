"""Bounded child-process boundary for both upload inspection and processing.

This is local-development containment. Production MUST additionally run this
worker in an unprivileged no-network container with private read-only inputs.
"""
from __future__ import annotations
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from .engine import ProcessorError

REPORT_LIMIT = 2 * 1024 * 1024
REQUEST_LIMIT = 512 * 1024


def _run(request: dict, timeout: int) -> dict:
    payload = json.dumps(request, ensure_ascii=False).encode('utf-8')
    if len(payload) > REQUEST_LIMIT:
        raise ProcessorError('invalid_parameters')
    project = Path(__file__).resolve().parent.parent
    # Parser processes must not inherit database, Telegram, signing or provider
    # credentials from the API/worker environment.
    environment = {key: os.environ[key] for key in
        ('PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'TMP', 'TEMP', 'SYSTEMROOT', 'PDFMASTER_SOFFICE_BIN','PDFMASTER_TESSERACT_BIN')
        if key in os.environ}
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    # Numeric image processing must fit the existing child-process budget.
    # OpenBLAS otherwise allocates a thread pool before OpenCV can limit it.
    environment['OPENBLAS_NUM_THREADS'] = '1'
    environment['OMP_NUM_THREADS'] = '1'
    # No request file is written: secrets, if present, travel only over stdin.
    with tempfile.TemporaryFile() as report:
        process = subprocess.Popen([sys.executable, '-m', 'processors'],
            stdin=subprocess.PIPE, stdout=report, stderr=subprocess.DEVNULL,
            cwd=project, start_new_session=True,
            env=environment)
        try:
            process.communicate(payload, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise ProcessorError('processor_timeout') from None
        finally:
            # Office launchers can leave descendants when their own timeout
            # fires. Remove the dedicated attempt group even after CLI exit.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if report.tell() > REPORT_LIMIT:
            raise ProcessorError('processor_report_limit')
        report.seek(0)
        try:
            result = json.loads(report.read(REPORT_LIMIT))
        except (ValueError, UnicodeError):
            raise ProcessorError('processor_failed') from None
    if not result.get('ok'):
        raise ProcessorError(result.get('error', 'processing_failed'))
    if process.returncode != 0:
        raise ProcessorError('processor_failed')
    return result['result']


def inspect_file_sandbox(path: str | Path, *, password: str | None = None, timeout: int = 90) -> dict:
    return _run({'operation': 'inspect', 'path': str(Path(path).absolute()), 'secret': password}, timeout)


def execute_sandbox(feature_id: str, input_paths: list[str | Path], parameters: dict,
                    output_dir: str | Path, *, secret: str | None = None, timeout: int = 90) -> dict:
    return _run({'operation': 'execute', 'feature_id': feature_id,
        'input_paths': [str(Path(p).absolute()) for p in input_paths],
        'parameters': parameters, 'output_dir': str(Path(output_dir).absolute()),
        'secret': secret}, timeout)
