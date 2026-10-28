"""Explicit disposable ETF probe. Standard library only; no subscription/cache."""
import contextlib
import json
from pathlib import Path
import re
import sys

if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dashboard.marketdata.wind_terminal_worker import (TrackedWind,daily,dataset,number,iso,safe_diagnostics)

FIELD=re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}')
CODE=re.compile(r'(?:5\d{5}\.SH|1[56]\d{4}\.SZ)')


def specification(value):
    """JSON is field metadata, never code. Unknown or guessed mappings stay absent."""
    if not value:return {}
    if value.get('schema')!='overview-etf-fields-v1':raise ValueError('fields_schema')
    result={}
    for kind in ('iopv','shares','pcf'):
        item=value.get(kind) or {}
        if not item:continue
        if not isinstance(item,dict) or not isinstance(item.get('definition_source'),str) or not item['definition_source'].strip():raise ValueError('field_definition_required')
        fields=item.get('fields') if kind=='pcf' else [item.get('field')]
        if not isinstance(fields,list) or not 1<=len(fields)<=8 or any(not isinstance(f,str) or not FIELD.fullmatch(f) for f in fields):raise ValueError('invalid_fields')
        options=item.get('options','')
        if not isinstance(options,str) or len(options)>512 or any(c in options for c in '\r\n\x00'):raise ValueError('invalid_options')
        if kind=='pcf' and not FIELD.fullmatch(str(item.get('dataset',''))):raise ValueError('invalid_dataset')
        if kind=='pcf' and not all(FIELD.fullmatch(str(item.get(f,''))) for f in ('date_field','code_field')):raise ValueError('pcf_identity_required')
        if kind=='shares' and item.get('units') not in ('shares','ten_thousand_shares','unknown'):raise ValueError('shares_units_required')
        result[kind]=dict(item)
    return result


class ProbeWind(TrackedWind):
    def wsd(self,codes,field,start,end,options):
        return self.call('wsd',(codes,field,start,end,options),stage='etf_daily_probe',field=field,codes_count=len(codes.split(',')))


def probe(w,request):
    spec=specification(request.get('fields'))
    codes=request['codes'];day=request['day'];previous=request['previous_day']
    if not 1<=len(codes)<=12 or len(set(codes))!=len(codes) or any(not CODE.fullmatch(s) for s in codes):raise ValueError('invalid_etfs')
    tracked=ProbeWind(w,request);checks={}
    try:
        tracked.start()
        def run(kind,work):
            try:checks[kind]=work()
            except Exception as exc:
                checks[kind]=dict(status='unavailable',error_type=type(exc).__name__)
                if tracked.diagnostics['steps'] and tracked.diagnostics['steps'][-1]['status']!='failed':tracked.warning(exc,'ETF能力测试')
        def nav():
            ns=daily(tracked,codes,'nav',day,'unit=1')
            cs=daily(tracked,codes,'close',day,'PriceAdj=U')
            valid=[s for s in codes if number(ns.get(s)) is not None and number(cs.get(s)) is not None and number(ns[s])>0 and number(cs[s])>0]
            return dict(status='complete' if len(valid)==len(codes) else 'partial',day=day,expected=len(codes),valid_pairs=len(valid),
                fields=['nav','close'],same_day=True,price_adjustment='none',intraday_iopv=False)
        run('close_nav',nav)
        if 'iopv' not in spec:checks['iopv']=dict(status='mapping_required',nonempty=None,reason='缺经核验IOPV字段定义；没有请求猜测字段')
        else:
            def iopv():
                field=spec['iopv']['field']
                response=tracked.call('wsq',(','.join(codes),field),stage='iopv_snapshot_probe',field=field,codes_count=len(codes))
                returned=[str(s).upper() for s in response.Codes];fields=[str(f).lower() for f in response.Fields]
                if set(returned)!=set(codes) or len(returned)!=len(codes) or fields!=[field.lower()] or len(response.Data)!=1 or len(response.Data[0])!=len(codes):raise ValueError('iopv_shape')
                count=sum(number(v) is not None and number(v)>0 for v in response.Data[0])
                return dict(status='values_returned_timing_unverified' if count else 'empty',field=field,expected=len(codes),nonempty=count,
                    source_timestamp_verified=False,premium_computed=False,subscription=False)
            run('iopv',iopv)
        if 'shares' not in spec:checks['net_creation']=dict(status='mapping_required',reason='缺份额字段/单位/拆分定义；没有用规模或成交量代替')
        else:
            def shares():
                item=spec['shares'];field=item['field'];values=[]
                for d in (previous,day):
                    options=item.get('options','').replace('{day}',d)
                    row=daily(tracked,codes,field,d,options)
                    values.append({s:number(row.get(s)) for s in codes})
                count=sum(all(v.get(s) is not None and v[s]>=0 for v in values) for s in codes)
                return dict(status='values_returned_definition_review_required' if count else 'empty',field=field,expected=len(codes),valid_two_day_pairs=count,
                    days=[previous,day],units=item['units'],net_flow_computed=False,split_adjustment_verified=False)
            run('net_creation',shares)
        if 'pcf' not in spec:checks['pcf']=dict(status='mapping_required',reason='缺带日PCF来源及字段；网页可达不代表解析成功')
        else:
            def pcf():
                item=spec['pcf'];valid=0;rows_count=0;nonempty=0
                for code in codes:
                    options=item.get('options','').replace('{day}',day).replace('{code}',code)
                    response=tracked.call('wset',(item['dataset'],options),stage='pcf_probe',dataset=item['dataset'],codes_count=1)
                    rows=dataset(response,'PCF');rows_count+=len(rows)
                    if rows and all(iso(r.get(item['date_field'].lower()))==day and str(r.get(item['code_field'].lower())).upper()==code for r in rows):valid+=1
                    nonempty+=sum(all(r.get(f.lower()) is not None and str(r.get(f.lower())).strip() for f in item['fields']) for r in rows)
                return dict(status='dated_rows_returned_definition_review_required' if valid else 'identity_unverified',day=day,expected=len(codes),
                    matching_codes=valid,rows=rows_count,nonempty_rows=nonempty,fields=item['fields'],creation_state_computed=False)
            run('pcf',pcf)
        return dict(checks=checks,diagnostics=safe_diagnostics(tracked.diagnostics))
    except Exception as exc:
        exc.diagnostics=safe_diagnostics(tracked.diagnostics);raise


def main():
    request=json.loads(sys.stdin.read());w=None
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from WindPy import w
            output=probe(w,request)
        output['ok']=True
    except Exception as exc:
        output=dict(ok=False,error_type=type(exc).__name__,diagnostics=safe_diagnostics(getattr(exc,'diagnostics',
            dict(steps=[dict(stage='import' if w is None else 'probe',status='failed',error_type=type(exc).__name__)]))))
    finally:
        if w is not None:
            try:
                with contextlib.redirect_stdout(sys.stderr):w.stop()
            except Exception:pass
    print(json.dumps(output,ensure_ascii=False,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
