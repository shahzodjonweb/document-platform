"""Trusted worker JSON/stdin transport. Never expose this as a public endpoint."""
from __future__ import annotations
import json
import os
import sys
from processors.env import env


def _setting(name, default, low, high):
    try:
        return min(high, max(low, int(env(name, default))))
    except ValueError:
        return default


def apply_limits():
    cpu_seconds = _setting('CPU_SECONDS', 85, 85, 2000)
    # 2 GiB, 3 GiB for the document scanner (processors/sandbox.child_limits).
    address_space = _setting('ADDRESS_SPACE_MB', 2048, 2048, 3072) * 1024 * 1024
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
        limits.append((resource.RLIMIT_AS, (address_space,) * 2))
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
            result = inspect_file(request['path'], request.get('secret'), allow_links=request.get('allow_links') is True)
        elif request.get('operation') == 'execute':
            result = execute(request['feature_id'], request['input_paths'],
                request.get('parameters', {}), request['output_dir'], secret=request.get('secret'),
                office_timeout=request.get('office_timeout', 60), deck_fonts=request.get('deck_fonts') is True,
                office_home=request.get('office_home'), pdfcraft=request.get('pdfcraft') is True)
        elif request.get('operation') == 'helper':
            from .helpers import run as helper
            result = helper(request.get('name'), request.get('input_paths'), request.get('parameters', {}),
                request['output_dir'], pdfcraft=request.get('pdfcraft') is True)
        else:
            raise ProcessorError('invalid_operation')
        json.dump({'ok': True, 'result': result}, sys.stdout)
        return 0
    except ProcessorError as error:
        json.dump({'ok': False, 'error': error.code, 'index': error.index}, sys.stdout)
    except Exception:
        json.dump({'ok': False, 'error': 'processor_failed'}, sys.stdout)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
