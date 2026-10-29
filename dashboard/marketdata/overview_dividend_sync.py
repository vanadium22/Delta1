"""Bounded share reader and local dividend publisher, with separate ownership."""
from datetime import datetime, timedelta
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')
    temporary.replace(path)


def stage_inputs(request):
    """This private reader writes only disposable staging files, never a store."""
    root = Path(request['staging'])
    root.mkdir(parents=True, exist_ok=True)
    progress = root/'progress.json'
    result = dict(files=[], unchanged=0, errors=[], complete=True, matched=0)
    started = time.monotonic()
    known = request.get('inventory', {})
    hashes = set(request.get('known_hashes', []))
    stop = lambda:bool(request.get('stop_file') and Path(request['stop_file']).exists())
    paths = []
    for directory in request['directories']:
        if stop():
            raise InterruptedError()
        try:
            for path in Path(directory).iterdir():
                if path.name.startswith(('~$', '.')) or not fnmatch.fnmatch(path.name, request['pattern']):
                    continue
                # Names can retain an old date. Only the validated Sheet1!B1
                # business date may decide whether an input is in this window.
                paths.append(path)
        except OSError as exc:
            result['errors'].append(dict(stage='share_listing', error_type=type(exc).__name__, winerror=getattr(exc, 'winerror', None)))
    result['matched'] = len(paths)
    result['matched_names'] = sorted((p.name for p in paths),reverse=True)[:12]
    for path in sorted(paths, key=lambda p:p.name, reverse=True):
        if stop():
            raise InterruptedError()
        if time.monotonic()-started > request.get('budget', 15) or len(result['files']) >= 400:
            result['complete'] = False
            break
        try:
            info = path.stat()
            key = str(path)
            token = [info.st_size, info.st_mtime_ns]
            previous = known.get(key, {})
            outside = previous.get('business_dates') and all(not request['start'] <= day <= request['end'] for day in previous['business_dates'])
            if previous.get('token') == token and (previous.get('sha256') in hashes or outside):
                result['unchanged'] += 1
                continue
            if not path.is_file() or not 0 < info.st_size <= 16*1024*1024:
                continue
            raw = path.read_bytes()
            after = path.stat()
            if token != [after.st_size, after.st_mtime_ns]:
                raise ValueError('source_changed')
            sha = hashlib.sha256(raw).hexdigest()
            staged = None
            if sha not in hashes:
                staged = root/sha/path.name
                staged.parent.mkdir(exist_ok=True)
                staged.write_bytes(raw)
                hashes.add(sha)
            result['files'].append(dict(source=key, token=token, sha256=sha, path=str(staged) if staged else None))
        except (OSError, ValueError) as exc:
            result['errors'].append(dict(stage='share_read', error_type=type(exc).__name__, winerror=getattr(exc, 'winerror', None)))
        _save(progress, result)
    if result['errors']:
        result['complete'] = False
    _save(progress, result)
    return result


def source_directories(config, start, end):
    from .overview_dividends import source_directory
    selected = source_directory(config)
    if not selected:
        return []
    root = Path(selected)
    if re.fullmatch(r'20\d{2}', root.name):
        return [str(root.parent/str(year)) for year in range(int(start[:4]), int(end[:4])+1)]
    return [str(root)]


def run_sync(config, local_root, *, now=None, stop_file=None, reader=None, publish=True):
    from .overview_dividends import DividendStore, directory, local_sources, stamp, records_from_file
    from .overview_percentiles import prior_days
    from .overview_windpy import run_readonly_worker
    from .bars import _atomic_bytes, _json_bytes
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    root = directory(config, local_root)
    root.mkdir(parents=True, exist_ok=True)
    store = DividendStore(root)
    state = dict(started_at=stamp(now), imported_files=0, inserted=0, unchanged=0, validated_files=0, outside_range_files=0, business_dates=[], errors=[], network_requested=False)
    stopped = lambda:bool(stop_file and Path(stop_file).exists())
    def ingest(path, *, business_window=None):
        if stopped():
            raise InterruptedError()
        value = store.import_file(path, now=now, business_window=business_window)
        state['imported_files'] += value['status'] == 'imported'
        state['inserted'] += value['inserted']
        state['unchanged'] += value['status'] == 'unchanged'
        state['outside_range_files'] += value['status'] == 'outside_range'
        return value
    try:
        if publish:
            for path in local_sources(config):
                try:
                    ingest(path)
                except InterruptedError:
                    raise
                except Exception as exc:
                    state['errors'].append(dict(stage='local_import', error_type=type(exc).__name__))
        day = now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        start = (datetime.fromisoformat(prior_days(day)[0])-timedelta(days=35)).date().isoformat()
        directories = source_directories(config, start, day)
        state.update(source_directories=directories,pattern=config.get('overview_dividend_pattern') or '指数基差情况_*.xlsx',
            requested_start=start,requested_end=day)
        inventory = read_json(root/'inventory.json').get('files', {})
        records = store.read()
        hashes = sorted({r['file_sha256'] for r in records})
        dates_by_hash = {}
        for record in records:
            dates_by_hash.setdefault(record['file_sha256'], set()).add(record['source_business_date'])
        with tempfile.TemporaryDirectory(prefix='reader-', dir=root) as tmp:
            request = dict(directories=directories, pattern=config.get('overview_dividend_pattern') or '指数基差情况_*.xlsx',
                staging=tmp, inventory=inventory, known_hashes=hashes, start=start, end=day,
                stop_file=str(stop_file) if stop_file else None, budget=15)
            state['network_requested'] = bool(directories)
            if reader:
                fetched = reader(request)
            elif not directories:
                fetched = dict(files=[], unchanged=0, matched=0, errors=[], complete=True)
            else:
                try:
                    result = run_readonly_worker([sys.executable, '-B', '-X', 'utf8', '-m', 'dashboard.marketdata.overview_dividend_sync', '--reader'],
                        request, stop_file or Path(tmp)/'stop', timeout=20)
                    if result.returncode:
                        raise ValueError('share_reader_failed')
                    fetched = json.loads(result.stdout)
                except subprocess.TimeoutExpired:
                    fetched = read_json(Path(tmp)/'progress.json')
                    fetched.update(complete=False, errors=[*fetched.get('errors', []), dict(stage='share_reader', error_type='TimeoutExpired')])
            state.update(source_files=fetched.get('matched', 0),matched_names=fetched.get('matched_names',[]),
                unchanged=state['unchanged']+fetched.get('unchanged', 0))
            state['errors'].extend(fetched.get('errors', []))
            for item in fetched.get('files', []):
                if stopped():
                    raise InterruptedError()
                try:
                    business_dates = sorted(dates_by_hash.get(item['sha256'], ()))
                    if item.get('path') and publish:
                        value=ingest(item['path'],business_window=(start,day))
                        business_dates=value.get('business_dates',business_dates)
                    elif item.get('path'):
                        checked=records_from_file(item['path'],first_seen=now)
                        if any(r['file_sha256'] != item['sha256'] for r in checked):
                            raise ValueError('staging_hash_mismatch')
                        business_dates=sorted({r['source_business_date'] for r in checked})
                        if any(start <= value <= day for value in business_dates):
                            state['validated_files']+=1
                        else:
                            state['outside_range_files']+=1
                    state['business_dates']=sorted(set(state['business_dates'])|{value for value in business_dates if start <= value <= day})
                    dates_by_hash[item['sha256']]=set(business_dates)
                    if publish:
                        inventory[item['source']] = dict({k:item[k] for k in ('token','sha256')},business_dates=business_dates)
                except Exception as exc:
                    state['errors'].append(dict(stage='share_import', error_type=type(exc).__name__))
            if publish and not stopped():
                _atomic_bytes(root/'inventory.json', _json_bytes(dict(files=inventory)))
            state['status'] = ('source_empty' if directories and not fetched.get('matched') and not state['errors'] else
                'complete' if fetched.get('complete') and not state['errors'] else 'partial' if state['inserted'] else 'unavailable')
            state['published'] = bool(publish)
            state['history_coverage_certified'] = False
    except InterruptedError:
        state.update(status='cancelled', published=False)
    except Exception as exc:
        state.update(status='unavailable', error_type=type(exc).__name__)
    state['published'] = bool(publish and state['inserted'])
    state['configuration_changed'] = False
    state['finished_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    if publish:
        _atomic_bytes(root/'status.json', _json_bytes(state))
    return state


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--reader', action='store_true')
    parser.add_argument('--local-root', type=Path)
    args = parser.parse_args()
    if args.reader:
        try:
            result = stage_inputs(json.load(sys.stdin))
        except Exception as exc:
            result = dict(complete=False, files=[], errors=[dict(stage='share_reader', error_type=type(exc).__name__)])
        print(json.dumps(result, ensure_ascii=False))
        return 0
    config = json.loads((args.local_root/'native.json').read_text(encoding='utf-8-sig'))
    from .overview_dividends import directory
    run_sync(config, args.local_root, stop_file=directory(config,args.local_root)/'stop.request')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
