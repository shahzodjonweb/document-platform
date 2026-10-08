"""Trusted worker JSON/stdin transport. Never expose this as a public endpoint."""
from __future__ import annotations
import json
import os
import sys


def apply_limits():
    try:
        cpu_seconds = max(85, int(os.environ.get('PDFMASTER_CPU_SECONDS', '85')))
    except ValueError:
        cpu_seconds = 85
    try:
        import resource
    except ImportError:
        # Non-POSIX deployments are not qualified for the production release.
        resource = None
    limits = [] if resource is None else [
        (resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5)),
        (resource.RLIMIT_FSIZE, (512 * 1024 * 1024,) * 2),
        (resource.RLIMIT_NOFILE, (256, 256)),
        (resource.RLIMIT_CORE, (0, 0))]
    if resource is not None and sys.platform.startswith('linux'):
        limits.append((resource.RLIMIT_AS, (2 * 1024 * 1024 * 1024,) * 2))
    for name, value in limits:
        # One limit the host refuses must not drop the others with it.
        try:
            resource.setrlimit(name, value)
        except (ValueError, OSError):
            pass
    os.umask(0o077)


def main():
    apply_limits()
    from .engine import ProcessorError, execute, inspect_file
    from .sandbox import REQUEST_LIMIT
    try:
        payload = sys.stdin.buffer.read(REQUEST_LIMIT + 1)
        if len(payload) > REQUEST_LIMIT:
            raise ProcessorError('invalid_parameters')
        request = json.loads(payload)
        if request.get('operation') == 'inspect':
            result = inspect_file(request['path'], request.get('secret'))
        elif request.get('operation') == 'execute':
            result = execute(request['feature_id'], request['input_paths'],
                request.get('parameters', {}), request['output_dir'], secret=request.get('secret'))
        else:
            raise ProcessorError('invalid_operation')
        json.dump({'ok': True, 'result': result}, sys.stdout)
        return 0
    except ProcessorError as error:
        json.dump({'ok': False, 'error': error.code}, sys.stdout)
    except Exception:
        json.dump({'ok': False, 'error': 'processor_failed'}, sys.stdout)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
