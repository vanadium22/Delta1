"""Run the full offline preflight and the App in one Python interpreter."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import runpy
import sys
import time


def run_module(name, arguments):
    previous = sys.argv
    sys.argv = [name, *arguments]
    try:
        runpy.run_module(name, run_name='__main__', alter_sys=True)
        return 0
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0 if exc.code is None else 1
    finally:
        sys.argv = previous


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--runtime', required=True, type=Path)
    args, app_arguments = parser.parse_known_args(argv)
    path = args.runtime / 'launcher.json'
    state = json.loads(path.read_text(encoding='utf-8-sig'))
    started = time.monotonic()

    def record(phase, **fields):
        state.update(phase=phase, updated_at=datetime.now(timezone.utc).isoformat(), **fields)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)

    preflight = ['--output', str(args.runtime / 'preflight.json')]
    for i, value in enumerate(app_arguments[:-1]):
        if value == '--local-root':
            preflight += ['--local-root', app_arguments[i + 1]]
            break
    record('preflight', startup_mode='shared_interpreter', process_started_at=datetime.now(timezone.utc).isoformat())
    try:
        with (args.runtime / 'preflight.log').open('w', encoding='utf-8') as stdout, \
             (args.runtime / 'preflight.stderr.log').open('w', encoding='utf-8') as stderr, \
             redirect_stdout(stdout), redirect_stderr(stderr):
            code = run_module('dashboard.app_check', preflight)
    except Exception as exc:
        record('preflight_failed', exit_code=1, error_type=type(exc).__name__)
        return 1
    seconds = round(time.monotonic() - started, 6)
    if code:
        record('preflight_failed', exit_code=code, preflight_seconds=seconds)
        return code
    record('app_running', preflight_seconds=seconds, app_entry_at=datetime.now(timezone.utc).isoformat())
    # The App still performs its own background gap/credential checks. Only the
    # already imported dependencies are reused; no cached pass or skipped check.
    timing = {'DELTA1_PROCESS_STARTED_MONOTONIC': str(started),
              'DELTA1_PREFLIGHT_SECONDS': str(seconds)}
    previous = {key: os.environ.get(key) for key in timing}
    os.environ.update(timing)
    try:
        code = run_module('dashboard.native.editions_current', app_arguments)
    except Exception as exc:
        record('app_failed', exit_code=1, error_type=type(exc).__name__)
        return 1
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    record('app_exited', exit_code=code)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
