"""Trusted worker JSON/stdin transport. Never expose this as a public endpoint."""
from __future__ import annotations
import json
import os
import sys


def apply_limits():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (85, 90))
        resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if sys.platform.startswith('linux'):
            resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 * 1024 * 1024,) * 2)
    except (ImportError, ValueError, OSError):
        # Non-POSIX deployments are not qualified for the production release.
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
