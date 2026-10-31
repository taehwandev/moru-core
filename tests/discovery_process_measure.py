"""Measure a single child process: wall time and child CPU time.

CPU figures come from the delta of resource.getrusage(RUSAGE_CHILDREN)
taken before and after subprocess.run. That counter is cumulative over all
reaped children of this process, so the deltas are only valid when the driver
is exclusive and serial: no other child may be spawned or waited on
concurrently. Wall minus CPU cannot tell scheduler delay from IO wait; do not
interpret it as either.
"""
import resource
import subprocess
import time


def run_measured(argv, *, env, cwd, timeout=20, input_bytes=None):
    """Run argv (no shell) and return (CompletedProcess, metrics).

    metrics holds wall_ms, user_ms, system_ms and cpu_ms (user + system) for
    the child only. stdout/stderr are captured as bytes; stdin is DEVNULL
    unless explicit synthetic input_bytes are supplied.
    A nonzero exit code is returned, not raised. TimeoutExpired and spawn
    errors propagate unchanged; there are no retries.
    """
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter_ns()
    completed = subprocess.run(
        list(argv),
        env=env,
        cwd=cwd,
        stdin=subprocess.DEVNULL if input_bytes is None else None,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        shell=False,
        check=False,
    )
    wall_ns = time.perf_counter_ns() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)

    user_ms = (after.ru_utime - before.ru_utime) * 1000.0
    system_ms = (after.ru_stime - before.ru_stime) * 1000.0
    metrics = {
        "wall_ms": wall_ns / 1_000_000.0,
        "user_ms": user_ms,
        "system_ms": system_ms,
        "cpu_ms": user_ms + system_ms,
    }
    return completed, metrics
