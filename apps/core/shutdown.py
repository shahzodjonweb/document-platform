"""Stop a job loop between jobs, never in the middle of one.

A deploy replaces the worker containers with `docker compose up`, which sends
SIGTERM. With Python's default handling the process died on the spot: the job
it was running stayed `running` until its lease lapsed (ten minutes or more),
and was then failed as `worker_interrupted` — a customer's deck lost to a
deploy. With this installed, SIGTERM only asks the loop to stop: the job in
hand runs to its end (a blocking provider read resumes after the handler,
PEP 475), nothing new is taken, and the loop returns. The container's
`stop_grace_period` (infra/production/compose.yaml) bounds the wait; a job
still running when it ends is killed and recovered by the lease sweep as
before.
"""
import signal
from contextlib import contextmanager


class Stop:
    requested = False

    def __bool__(self):
        return self.requested


@contextmanager
def graceful_stop():
    stop = Stop()

    def request(signum, frame):
        stop.requested = True

    try:
        previous = signal.signal(signal.SIGTERM, request)
    except ValueError:
        # Not the main thread (a loop run from a test or a thread pool): there
        # is no process signal to listen for, so the loop runs as before.
        yield stop
        return
    try:
        yield stop
    finally:
        signal.signal(signal.SIGTERM, previous)
