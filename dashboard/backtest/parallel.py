"""Bounded spawn workers for read/compute tasks; cancellation never kills writers."""
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import multiprocessing as mp
import os
from pathlib import Path
import sys
import threading

from .models import check_cancelled


_CANCEL = None
_LOCAL = threading.local()


def _initialize(cancel_event):
    global _CANCEL
    _CANCEL = cancel_event


def worker_cancel_event():
    return getattr(_LOCAL, "cancel", _CANCEL)


def _invoke(function, payload):
    check_cancelled(_CANCEL)
    return os.getpid(), function(payload)


def worker_count(tasks, requested=0, work_units=0):
    if tasks < 2 or requested == 1:
        return 1
    if requested:
        return min(tasks, requested)
    main_file = getattr(sys.modules.get("__main__"), "__file__", None)
    if os.name == "nt" and (not main_file or not Path(main_file).is_file()):
        return 1  # Interactive cells have no importable spawn entry point.
    if work_units < 250_000:
        return 1  # Starting Python workers costs more than a small vectorized job.
    cpu = getattr(os, "process_cpu_count", os.cpu_count)() or 1
    return min(tasks, cpu, 4)


def process_map(function, tasks, *, workers=0, work_units=0, cancel_event=None, progress=None, stage="parallel"):
    """Return in input order; at most twice the worker count is queued at once."""
    tasks = list(tasks)
    count = worker_count(len(tasks), workers, work_units)
    if count == 1:
        values = []
        for i, task in enumerate(tasks):
            check_cancelled(cancel_event)
            # A serial task also receives the caller's cancellation event.
            previous = getattr(_LOCAL, "cancel", None)
            _LOCAL.cancel = cancel_event
            try:
                values.append(function(task))
            finally:
                _LOCAL.cancel = previous
            if progress:
                progress(dict(stage=stage, done=i + 1, total=len(tasks), workers=1))
        return values, dict(workers=1, worker_pids=[os.getpid()])
    context = mp.get_context("spawn")
    shared_cancel = context.Event()
    executor = ProcessPoolExecutor(max_workers=count, mp_context=context,
                                   initializer=_initialize, initargs=(shared_cancel,))
    pending, output, pids = {}, [None] * len(tasks), set()
    iterator = iter(enumerate(tasks))
    def submit_next():
        item = next(iterator, None)
        if item is None:
            return False
        i, payload = item
        pending[executor.submit(_invoke, function, payload)] = i
        return True
    completed = 0
    try:
        for _ in range(min(len(tasks), count * 2)):
            submit_next()
        while pending:
            check_cancelled(cancel_event)
            ready, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
            for future in ready:
                i = pending.pop(future)
                pid, output[i] = future.result()
                pids.add(pid)
                completed += 1
                if progress:
                    progress(dict(stage=stage, done=completed, total=len(tasks), workers=count))
                submit_next()
        return output, dict(workers=count, worker_pids=sorted(pids))
    finally:
        shared_cancel.set()
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
