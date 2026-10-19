"""Bounded native-history gap repair over the existing network route; no VPN changes."""
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

import pandas as pd

from .bars import _atomic_bytes, _json_bytes, _row_key
from .ddb_import import convert_file
from dashboard.native.instruments import UNDERLYINGS


def gap_plan(stores, metadata, days, start, end):
    """Use actual observed sessions, never weekdays or filled calendar estimates."""
    counts=Counter()
    for store in stores.values():
        for part in store.snapshot()['parts']:
            counts[part['instrument_id'],part['frequency'],part['trade_date']]+=part['rows']
    jobs=[]
    for day in sorted(set(days),reverse=True):
        if not start<=day<=end:continue
        symbols=[v[0] for v in UNDERLYINGS.values()]+[s for s,r in metadata.items() if r['listing_date']<=day<=r['expiry_date']]
        for frequency,required in [('1d',1),('1m',240)]:
            for symbol in symbols:
                if counts[symbol,frequency,day]<required:
                    jobs.append(dict(symbol=symbol,frequency=frequency,day=day,
                                     observed=counts[symbol,frequency,day],expected=required))
    return jobs


def repair(stores, metadata, destination, start, end, *, limit=80, budget=120):
    from index_strategy.history.downloader import Client, DEFAULT_CONFIG
    from index_strategy.history.catalog import route
    from .history_backfill import missing_only
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    result=dict(state='unavailable',inserted=0,queries=0,network_policy='existing_route_only_no_vpn_change')
    days={p['trade_date'] for s in stores.values() for p in s.snapshot()['parts'] if p['frequency']=='1d'}
    jobs=gap_plan(stores,metadata,days,start,end)
    _atomic_bytes(destination/'pending.json',_json_bytes({'start':start,'end':end,'jobs':jobs}))
    result['pending_symbol_days']=len(jobs)
    client=None
    try:
        from index_strategy.history.credentials import load_config
        config=load_config(DEFAULT_CONFIG)
        with socket.create_connection((config['host'],int(config['port'])),timeout=3):pass
        try:
            import dolphindb as ddb
        except ImportError:
            # The dashboard's Python and the corporate SDK environment are
            # deliberately separate. Use the existing isolated environment.
            from index_strategy.history.downloader import PUBLIC_ROOT
            interpreter=Path(os.environ.get('SWHY_HISTORY_PYTHON',str(PUBLIC_ROOT/'dolphindb_data/.venv/Scripts/python.exe')))
            if not interpreter.is_file() or interpreter.resolve()==Path(sys.executable).resolve():
                raise RuntimeError('缺少 DolphinDB SDK 环境，请配置 SWHY_HISTORY_PYTHON')
            request=destination/'request.json'
            _atomic_bytes(request,_json_bytes(dict(roots={k:str(v.root) for k,v in stores.items()},metadata=metadata,
                destination=str(destination),start=start,end=end,limit=limit,budget=budget)))
            completed=subprocess.run([str(interpreter),'-B','-s','-X','utf8','-m','dashboard.marketdata.history_remote','--request',str(request)],
                cwd=Path(__file__).resolve().parents[2],capture_output=True,text=True,encoding='utf8',
                timeout=budget+180,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if completed.returncode:raise RuntimeError('独立历史 SDK 查询失败；原始进程输出不写入日志')
            result=json.loads((destination/'status.json').read_text(encoding='utf8'))
            return result
        # Reuse the audited query/identity/unit methods, with an explicitly
        # direct session. Calling Client() would invoke its VPN lifecycle helper.
        client=Client.__new__(Client)
        client.config=config;client._closed=False;client._vpn_entered=False
        client.mapping_cache={};client.source_cache=set()
        client.session=ddb.session(enableSSL=config.get('enable_ssl',True))
        if not client.session.connect(config['host'],config['port'],config['username'],
                os.environ.get('DDB_PASSWORD') or config.get('password',''),readTimeout=15,writeTimeout=10):
            raise RuntimeError('历史库登录失败')
        started=time.monotonic()
        _,source=route('000300.SH','1d')
        days.update(str(d) for d in client.available_dates(source,'000300.SH',date.fromisoformat(start),date.fromisoformat(end)))
        jobs=gap_plan(stores,metadata,days,start,end)
        _atomic_bytes(destination/'pending.json',_json_bytes({'start':start,'end':end,'jobs':jobs}))
        result['pending_symbol_days']=len(jobs)
        pending={k:[] for k in stores};evidence=[]
        for job in jobs[:limit]:
            if time.monotonic()-started>=budget:break
            symbol,frequency,day=job['symbol'],job['frequency'],job['day']
            _,source=route(symbol,frequency)
            frame,info=client.fetch(source,symbol,date.fromisoformat(day),
                dict(asset='auto',depth=0,oi=True,mode='native',frequency=frequency))
            result['queries']+=1
            if frame.empty:continue
            frame=frame.copy();frame['source_symbol']=symbol;frame['symbol']=symbol
            frame['quality']='complete'
            path=destination/'downloads'/(uuid.uuid4().hex+'.parquet');path.parent.mkdir(exist_ok=True)
            frame.to_parquet(path,index=False)
            item=dict(file=str(path),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      rows=len(frame),schema_version=2,source_symbol=symbol,frequency=frequency,trading_date=day,
                      downloaded_at=datetime.now(timezone.utc).isoformat(),**info)
            _atomic_bytes(path.with_suffix('.json'),_json_bytes(item))
            rows,skipped=convert_file(item)
            kind='cn_index_future' if symbol.endswith('.CFE') else 'cn_index'
            pending[kind].extend(rows);evidence.append(dict(file=str(path),sha256=item['sha256'],skipped=skipped))
        result['datasets']={}
        for kind,rows in pending.items():
            if not rows:continue
            store=stores[kind]
            pairs={(r['instrument_id'],r['frequency']) for r in rows}
            snap=store.snapshot()
            subset={**snap,'parts':[p for p in snap['parts'] if (p['instrument_id'],p['frequency']) in pairs]}
            existing={}
            for row in store._rows(subset):
                key=_row_key(row)
                if key not in existing or row['revision']>existing[key]['revision']:existing[key]=row
            chosen,details=missing_only(rows,existing)
            template=next(iter(store.descriptor['instruments'].values()))
            registration={s:{**template,'underlying_id':UNDERLYINGS[s[:2]][0]} for s in {r['instrument_id'] for r in chosen}
                          if s not in store.descriptor['instruments']}
            if registration:store.register_instruments(registration)
            committed=store.commit(chosen,checkpoint={'remote_gap_repair':evidence})
            result['datasets'][kind]={**committed,**details};result['inserted']+=committed['inserted']
        remaining=gap_plan(stores,metadata,days,start,end)
        result.update(state='partial' if remaining else 'complete',pending_symbol_days=len(remaining),evidence=evidence)
        _atomic_bytes(destination/'pending.json',_json_bytes({'start':start,'end':end,'jobs':remaining}))
    except (OSError,RuntimeError,ValueError,KeyError,ImportError,subprocess.TimeoutExpired) as exc:
        result['reason']=type(exc).__name__+': 历史查询或校验失败，原始错误已隐藏'
    finally:
        if client is not None:client.close()
        result['checked_at']=datetime.now(timezone.utc).isoformat()
        _atomic_bytes(destination/'status.json',_json_bytes(result))
    return result


if __name__=='__main__':
    import argparse
    from .bars import BarDataset
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    args=parser.parse_args();request=json.loads(Path(args.request).read_text(encoding='utf8'))
    repair({k:BarDataset(v) for k,v in request.pop('roots').items()},**request)
