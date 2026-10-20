"""Read-only two-sample diagnosis; no configuration preparation or collection."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def same_cell(actual, expected):
    # Excel/PowerShell JSON round-trips a double through 15-17 decimal digits.
    # This comparison does not affect calculations or missing-value semantics.
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-10)
    return actual == expected


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def cache_state(root):
    path = Path(root) / 'live/quotes.sqlite3'
    result = dict(path=str(path), exists=path.is_file())
    if not path.is_file():
        return result
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=3)) as con:
            con.execute('PRAGMA query_only=ON')
            columns = {r[1] for r in con.execute('PRAGMA table_info(quotes)')}
            wanted = [c for c in ('sequence', 'symbol', 'source_event_time', 'received_at', 'close') if c in columns]
            row = con.execute('SELECT '+','.join(wanted)+' FROM quotes ORDER BY sequence DESC LIMIT 1').fetchone()
            result['tail'] = dict(zip(wanted, row)) if row else None
        result['mtime_utc'] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except (OSError, sqlite3.Error) as exc:
        result['error'] = str(exc)
    return result


def sample(run_file):
    run = read_json(run_file)
    keys=('run_id','output','launcher_pid','producer_pid','excel_pid','hwnd','state','heartbeat_at',
          'last_write_at','last_save_at','writes','saves','error','requested_python','read_only_cache')
    result = dict(run={k:run.get(k) for k in keys}, observed_at=datetime.now(timezone.utc).isoformat())
    result['run']['heartbeat_age_seconds']=round((datetime.now(timezone.utc)-datetime.fromisoformat(run['heartbeat_at'])).total_seconds(),1)
    try:
        feed = read_json(run['feed'])
        status_path=Path(run['feed']).with_suffix('.status.json')
        if status_path.is_file():
            result['calculation']=read_json(status_path)
        rows = feed['sheets']['数字看板']
        result['feed'] = {k: feed.get(k) for k in ('generated_at', 'ready', 'calculation_completed_at',
                         'calculation_seconds', 'acquisition', 'collector', 'evidence', 'runtime')}
        if result['feed']['evidence']:
            result['feed']['evidence']={k:v for k,v in result['feed']['evidence'].items() if k!='rows'}
        result['feed']['rows'] = len(rows)
        result['feed']['representative'] = {a: rows[0][i] for a, i in
            (('C7', 2), ('D7', 3), ('E7', 4), ('J7', 9), ('L7', 11))} if rows else {}
        runtime = feed.get('runtime', {})
        if runtime.get('realtime_root'):
            result['cache'] = cache_state(runtime['realtime_root'])
        if runtime.get('config_path'):
            p = Path(runtime['config_path'])
            selected = ('history_roots', 'realtime_root', 'reference_file', 'dividend_root',
                        'dividend_scenario_file', 'allow_unverified', 'dividend_mode')
            result['config'] = {k: read_json(p).get(k) for k in selected}
            original = p.parent.parent/'native.json'
            if p.parent.name == 'numeric_excel' and original.is_file():
                original_value = read_json(original)
                result['original_config_path_differences'] = [k for k in selected if original_value.get(k) != result['config'][k]]
    except (OSError, ValueError, KeyError) as exc:
        result['feed_error'] = str(exc)
    try:
        observed = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            str(ROOT/'dashboard/excel_numeric/inspect.ps1'), '-RunFile', str(run_file)],
            capture_output=True, timeout=15, creationflags=0x08000000 if sys.platform=='win32' else 0)
        result['window'] = json.loads(observed.stdout.decode('utf-8-sig'))
        result['cells_match_feed'] = (result['window'].get('attached', False) and
            all(same_cell(result['window']['cells'].get(k), v) for k, v in result.get('feed', {}).get('representative', {}).items()))
        if not result.get('feed',{}).get('representative'):
            result['cells_match_feed']=None
        after=read_json(run['feed'])
        if after.get('generated_at')!=result.get('feed',{}).get('generated_at'):
            result['sample_spanned_calculation']=True
            result['cells_match_feed']=None  # Concurrent publication is inconclusive, not a write failure.
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        result['window'] = dict(attached=False, error=str(exc))
    try:
        result['file_mtime_utc'] = datetime.fromtimestamp(Path(run['output']).stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        result['file_mtime_utc'] = None
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', help='Run identifier printed in the workbook; prefix accepted only when unique')
    parser.add_argument('--samples', type=int, default=2)
    parser.add_argument('--interval', type=float, default=10)
    args = parser.parse_args(argv)
    if not 1 <= args.samples <= 3 or not 0 <= args.interval <= 30:
        parser.error('samples must be 1..3; interval must be 0..30')
    runs = sorted((ROOT/'dashboard/runtime/numeric_live').glob('*/run.json'), key=lambda p:p.stat().st_mtime, reverse=True)
    if args.run_id:
        runs = [p for p in runs if p.parent.name.startswith(args.run_id)]
    else:
        active = []
        for p in runs:
            try:
                r=read_json(p)
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(r['heartbeat_at'])).total_seconds()
                if r.get('state') not in ('stopped', 'failed') and age < 30:
                    active.append(p)
            except (ValueError, KeyError, OSError):
                continue
        runs = active or runs[:1]
    if len(runs) != 1:
        print(json.dumps(dict(message='没有唯一的运行记录；旧启动器需更新重启，多个运行请用窗口运行号指定 --run-id。',
                              candidates=[p.parent.name for p in runs]), ensure_ascii=False))
        return 1
    def git(*cmd):
        return subprocess.check_output(['git', '-C', str(ROOT), *cmd], text=True).strip()
    print(json.dumps(dict(repo=str(ROOT), head=git('rev-parse','HEAD'), branch=git('branch','--show-current'),
                          diagnostic_python=sys.executable, run_id=runs[0].parent.name), ensure_ascii=False), flush=True)
    for i in range(args.samples):
        if i: time.sleep(args.interval)
        print(json.dumps(sample(runs[0]), ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
