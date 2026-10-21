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


def execution_timeout(feature_id: str, input_count: int) -> int:
    """Wall-clock budget for one sandbox run.

    Document scanning costs a few seconds per photograph, so a job of fifty
    photos cannot share the single-file budget. The job lease is ten minutes;
    the cap leaves time to store the result.

    Measured on an M2 Pro (two scanner threads, real sandbox): models load in
    0.25 CPU-s; a 960x1280 photo takes 2.5 CPU-s, a 12 MP photo 3.8-4.1
    CPU-s. Fifty photos (one in five 12 MP) took 62 s and 138 CPU-s, fifty
    12 MP photos 81 s and 193 CPU-s. Under a CPU quota the wall time is at
    least CPU-s / quota: 129 s at the worker's and batches' 1.5 CPUs for the
    worst job, 387 s at 0.5, too close to the 450 s cap for slower cores.
    """
    if feature_id == 'pdf.images_to_pdf':
        return min(450, 60 + 10 * max(1, int(input_count)))
    return 90


def child_limits(feature_id: str, timeout: int) -> dict:
    """CPU seconds and address space (MiB) for one child (processors/__main__.py).

    The document scanner runs two threads, so its CPU budget is twice the
    wall-clock one. Its address space is 3 GiB instead of 2: a 12 MP photo
    needs ~1.5 GB resident (macOS), and on Linux the libraries, thread stacks
    and malloc arenas count as well. The containers' mem_limit bounds what is
    really used.
    """
    if feature_id == 'pdf.images_to_pdf':
        return {'cpu_seconds': 2 * max(85, int(timeout) - 5), 'address_space_mb': 3072}
    return {'cpu_seconds': max(85, int(timeout) - 5), 'address_space_mb': 2048}


def _run(request: dict, timeout: int) -> dict:
    payload = json.dumps(request, ensure_ascii=False).encode('utf-8')
    if len(payload) > REQUEST_LIMIT:
        raise ProcessorError('invalid_parameters')
    project = Path(__file__).resolve().parent.parent
    # Parser processes must not inherit database, Telegram, signing or provider
    # credentials from the API/worker environment.
    environment = {key: os.environ[key] for key in
        ('PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'TMP', 'TEMP', 'SYSTEMROOT', 'PDFMASTER_SOFFICE_BIN','PDFMASTER_TESSERACT_BIN',
         'SCANNER_MODELS')
        if key in os.environ}
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    # Numeric image processing must fit the existing child-process budget.
    # OpenBLAS otherwise allocates a thread pool before OpenCV can limit it.
    environment['OPENBLAS_NUM_THREADS'] = '1'
    environment['OMP_NUM_THREADS'] = '1'
    # The document scanner's networks and OpenCV run on two threads: the
    # worker has 1.5 CPUs, a scan takes 2.0 s instead of 2.8 s (M2 Pro) and
    # the pages are byte-identical to one thread. glibc would otherwise give
    # each thread its own malloc arena under the address-space limit.
    environment['SCANNER_THREADS'] = '2'
    environment['MALLOC_ARENA_MAX'] = '2'
    # The child's CPU limit follows the wall-clock budget of this run.
    limits = child_limits(request.get('feature_id', ''), timeout)
    environment['PDFMASTER_CPU_SECONDS'] = str(limits['cpu_seconds'])
    environment['PDFMASTER_ADDRESS_SPACE_MB'] = str(limits['address_space_mb'])
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


def inspect_file_sandbox(path: str | Path, *, password: str | None = None, timeout: int = 90, allow_links: bool = False) -> dict:
    request = {'operation': 'inspect', 'path': str(Path(path).absolute()), 'secret': password}
    if allow_links:
        request['allow_links'] = True
    return _run(request, timeout)


def execute_sandbox(feature_id: str, input_paths: list[str | Path], parameters: dict,
                    output_dir: str | Path, *, secret: str | None = None, timeout: int = 90) -> dict:
    return _run({'operation': 'execute', 'feature_id': feature_id,
        'input_paths': [str(Path(p).absolute()) for p in input_paths],
        'parameters': parameters, 'output_dir': str(Path(output_dir).absolute()),
        'secret': secret}, timeout)
