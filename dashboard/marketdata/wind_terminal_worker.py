"""Standard-library-only, read-only WindPy reference worker. Never WSQ/WSI or VPN.

Run in the user's existing Wind Python WITHOUT -s: WindPy is often registered
in the user site. No pandas, Qt, Oracle driver, installs or database credentials.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
import contextlib
import json
import math
import os
from pathlib import Path
import re
import sys

ROOTS={'IF':'000300.SH','IH':'000016.SH','IC':'000905.SH','IM':'000852.SH'}
COUNTS={'IF':300,'IH':50,'IC':500,'IM':1000}
NAMES={'沪深300':'IF','上证50':'IH','中证500':'IC','中证1000':'IM'}
SECURITY=re.compile(r'[0-9]{6}\.(?:SH|SZ)')
VALIDATION_CODES={
    'Wind数据集字段不一致':'dataset_fields_mismatch',
    'Wind数据集长度不一致':'dataset_shape_mismatch',
    'Wind截面代码或字段不匹配':'cross_section_identity_mismatch',
    'Wind截面长度不一致':'cross_section_shape_mismatch',
    'Wind日频日期或代码不匹配':'daily_date_or_codes_mismatch',
    'Wind单日日频矩阵不匹配':'daily_shape_mismatch',
    'Wind成分权重无效':'index_weights_invalid',
    'Wind完整指数权重未取得':'index_weights_incomplete',
    'Wind成分数量未匹配指数样本数':'member_count_mismatch',
    'Wind权重日期不匹配':'weight_date_mismatch',
}


class WindError(Exception):
    pass


def error_code(value):
    """Keep the numeric Wind code, never its Data/error-message payload."""
    try:
        return int(value) if not isinstance(value,bool) and re.fullmatch(r'-?\d{1,12}',str(value)) else None
    except (TypeError,ValueError):return None


def connected(w):
    try:
        value=w.isconnected()
        return value if isinstance(value,bool) else None
    except Exception:return None


def safe_diagnostics(value):
    """Typed allowlist for IPC/status/report export; SDK exception text is excluded."""
    if not isinstance(value,dict):return {}
    output={}
    for key in ('provider','python','requested_day','stage','tracking_field','aum_field','aum_unit','etf_sector'):
        item=value.get(key)
        if isinstance(item,str) and len(item)<=512 and not any(c in item for c in '\r\n'):output[key]=item
    for key in ('user_site_enabled','connected_before','connected_after'):
        if value.get(key) is None or isinstance(value.get(key),bool):output[key]=value.get(key)
    for name in ('steps','failures','etf_universe_attempts','tracking_attempts'):
        rows=value.get(name)
        if not isinstance(rows,list):continue
        safe=[]
        for row in rows[:256]:
            if not isinstance(row,dict):continue
            entry={}
            for key in ('stage','operation','dataset','status','root','index_id','field','sector','day','started_at','finished_at','error_type','reason_code'):
                item=row.get(key)
                if isinstance(item,str) and len(item)<=128 and re.fullmatch(r'[\w .:+/\-()\u4e00-\u9fff]+',item):entry[key]=item
            for key in ('error_code','codes_count','batch','candidates','matching','unresolved','expected','actual'):
                item=error_code(row.get(key))
                if item is not None:entry[key]=item
            for key in ('connected_before','connected_after'):
                if key in row and (row[key] is None or isinstance(row[key],bool)):entry[key]=row[key]
            fields=row.get('returned_fields')
            if isinstance(fields,list):entry['returned_fields']=[s for s in fields[:30] if isinstance(s,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',s)]
            dates=row.get('returned_dates')
            if isinstance(dates,list):entry['returned_dates']=[s for s in dates[:5] if isinstance(s,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',s)]
            sample=row.get('unresolved_sample')
            if isinstance(sample,list):entry['unresolved_sample']=[s for s in sample[:10] if isinstance(s,str) and SECURITY.fullmatch(s)]
            safe.append(entry)
        output[name]=safe
    return output


class TrackedWind:
    """Record low-frequency call context before invoking the existing terminal."""
    def __init__(self,w,request):
        self.w=w;self.request=request
        self.diagnostics=dict(provider='WindPy',python=sys.executable,user_site_enabled=not bool(sys.flags.no_user_site),
            requested_day=request.get('day'),stage=request.get('stage','all'),connected_before=connected(w),steps=[],failures=[])

    def checkpoint(self):
        if not self.request.get('progress_file'):return
        path=Path(self.request['progress_file'])
        try:
            temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(safe_diagnostics(self.diagnostics),ensure_ascii=False),encoding='utf8')
            os.replace(temporary,path)
        except OSError:pass  # Scratch evidence must not interrupt a reference read.

    def call(self,operation,args,**context):
        entry=dict(operation=operation,day=self.request['day'],started_at=datetime.now(timezone.utc).isoformat(),
                   connected_before=connected(self.w),status='started',**context)
        self.diagnostics['steps'].append(entry)
        self.checkpoint()
        try:
            result=getattr(self.w,operation)(*args) if operation!='start' else self.w.start(waitTime=10,showmenu=False)
            entry.update(error_code=error_code(getattr(result,'ErrorCode',None)),status='returned')
            checked(result,entry['stage'])
            try:entry['returned_fields']=[str(f).lower() for f in getattr(result,'Fields',[])]
            except TypeError:entry['returned_fields']=[]
            returned_dates=[]
            try:stamps=tuple(getattr(result,'Times',()))[:5]
            except TypeError:stamps=()
            for stamp in stamps:
                try:returned_dates.append(iso(stamp))
                except (ValueError,TypeError):pass
            if returned_dates:entry['returned_dates']=returned_dates
            return result
        except Exception as exc:
            entry.update(status='failed',error_type=type(exc).__name__,
                         reason_code='wind_error_code' if isinstance(exc,WindError) else 'sdk_exception')
            self.diagnostics['failures'].append(dict(entry))
            error=WindError('Wind低频调用失败：'+entry['stage']);error.diagnostics=self.diagnostics
            raise error from None
        finally:
            entry.update(finished_at=datetime.now(timezone.utc).isoformat(),connected_after=connected(self.w))
            if entry.get('status')=='failed':self.diagnostics['failures'][-1]=dict(entry)
            self.diagnostics['connected_after']=entry['connected_after']
            self.checkpoint()

    def start(self,**kwargs):
        result=self.call('start',(),stage='connect')
        if self.diagnostics.get('connected_after') is False:
            self.warning(ValueError(),'连接状态未就绪')
            raise WindError('Wind连接状态未就绪')
        return result
    def wset(self,kind,options):
        parts=dict(s.split('=',1) for s in options.split(';') if '=' in s)
        context=dict(stage='index_weights' if kind=='indexconstituent' else 'etf_universe',dataset=kind)
        if kind=='indexconstituent':context.update(index_id=parts.get('windcode'),root=next((r for r,c in ROOTS.items() if c==parts.get('windcode')),None))
        else:context['sector']=parts.get('sector')
        return self.call('wset',(kind,options),**context)
    def wss(self,codes,field,options):
        return self.call('wss',(codes,field,options),stage='industry' if field==self.request.get('config',{}).get('industry_field','industry_sw') else 'etf_tracking',field=field,codes_count=len(codes.split(',')))
    def wsd(self,codes,field,start,end,options):
        return self.call('wsd',(codes,field,start,end,options),stage='anchor_close' if field=='close' else 'etf_scale',field=field,codes_count=len(codes.split(',')))

    def warning(self,exc,label):
        entry=self.diagnostics['steps'][-1]
        if entry.get('status')!='failed':
            entry.update(status='invalid_response',reason_code=VALIDATION_CODES.get(str(exc),'response_validation'),error_type=type(exc).__name__)
            self.diagnostics['failures'].append(dict(entry))
        self.checkpoint()
        # These are application labels, not str(exc) or Wind Data/connection text.
        return label+'：'+('样本数不匹配，' if 'expected' in entry else '')+entry['stage']+'，'+entry.get('reason_code','response_validation')


def checked(result,label):
    code=getattr(result,'ErrorCode',None)
    if code!=0:raise WindError(label+' ErrorCode='+str(code))
    return result


def number(value):
    if isinstance(value,bool):return None
    try:value=float(value)
    except (TypeError,ValueError,OverflowError):return None
    return value if math.isfinite(value) else None


def iso(value):
    if isinstance(value,(date,datetime)):return value.strftime('%Y-%m-%d')
    value=str(value).strip()
    if re.fullmatch(r'\d{8}',value):return datetime.strptime(value,'%Y%m%d').date().isoformat()
    return date.fromisoformat(value[:10]).isoformat()


def dataset(result,label):
    checked(result,label)
    fields=[str(f).lower() for f in result.Fields]
    if len(fields)!=len(set(fields)) or len(result.Data)!=len(fields):raise ValueError('Wind数据集字段不一致')
    count=len(result.Data[0]) if fields else 0
    if count>5000 or any(len(c)!=count for c in result.Data):raise ValueError('Wind数据集长度不一致')
    return [dict(zip(fields,values)) for values in zip(*result.Data)]


def wss(w,codes,field,options,stop=lambda:False):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',field):raise ValueError('Wind字段无效')
    result={}
    for start in range(0,len(codes),100):
        if stop():raise InterruptedError()
        batch=codes[start:start+100]
        response=checked(w.wss(','.join(batch),field,options),'WSS '+field)
        fields=[str(f).lower() for f in response.Fields]
        returned=[str(c).upper() for c in response.Codes]
        if field.lower() not in fields or len(set(returned))!=len(returned) or set(returned)!=set(batch):
            raise ValueError('Wind截面代码或字段不匹配')
        values=response.Data[fields.index(field.lower())]
        if len(values)!=len(returned):raise ValueError('Wind截面长度不一致')
        result.update(zip(returned,values))
    return result


def daily(w,codes,field,day,options,stop=lambda:False):
    """One dated point per code. No carry-forward or realtime Wind calls."""
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',field):raise ValueError('Wind字段无效')
    result={}
    for start in range(0,len(codes),100):
        if stop():raise InterruptedError()
        batch=codes[start:start+100]
        value=checked(w.wsd(','.join(batch),field,day,day,options+';Fill=Blank;Days=Trading'),'WSD '+field)
        returned=[str(c).upper() for c in value.Codes]
        if [iso(t) for t in value.Times]!=[day] or set(returned)!=set(batch) or len(returned)!=len(batch):
            raise ValueError('Wind日频日期或代码不匹配')
        if [str(f).lower() for f in value.Fields]!=[field.lower()] or len(value.Data)!=len(returned) or any(len(v)!=1 for v in value.Data):
            raise ValueError('Wind单日日频矩阵不匹配')
        result.update((s,v[0]) for s,v in zip(returned,value.Data))
    return result


def refresh(w,request,stop=lambda:False):
    tracked=TrackedWind(w,request)
    try:return _refresh(tracked,request,stop)
    except Exception as exc:
        if isinstance(exc,InterruptedError):error=exc
        else:error=WindError('Wind低频资料未完成；查看安全分阶段诊断')
        error.diagnostics=safe_diagnostics(tracked.diagnostics)
        raise error from None


def _refresh(w,request,stop):
    checked(w.start(waitTime=10,showmenu=False),'Wind连接')
    old=request.get('old') or {};config=request.get('config') or {}
    day=request['day'];stamp=request['fetched_at'];warnings=[]
    output=deepcopy(old) if old else dict(schema='overview-reference-v1',indices={},etfs={})
    output['fetched_at']=stamp;mapping=deepcopy(old.get('industries',{}));symbols=set();changed=0
    diagnostics=w.diagnostics;stage=request.get('stage','all')
    if stage not in ('all','connect','indices','etfs'):raise ValueError('低频检查阶段无效')
    if stage=='connect':return dict(data=output,diagnostics=safe_diagnostics(diagnostics))
    for root,index in (ROOTS.items() if stage in ('all','indices') else []):
        if stop():raise InterruptedError()
        try:
            rows=dataset(w.wset('indexconstituent',f'date={day};windcode={index}'),'WSET indexconstituent')
            members=[];dates=set()
            for row in rows:
                code=str(row.get('wind_code','')).upper();weight=number(row.get('i_weight'))
                if not SECURITY.fullmatch(code) or weight is None or weight<0:raise ValueError('Wind成分权重无效')
                if row.get('date') is not None:dates.add(iso(row['date']))
                members.append(dict(symbol=code,name=str(row.get('sec_name') or code),weight_pct=weight,industry=None))
            if not members or len({r['symbol'] for r in members})!=len(members) or not 99<=sum(r['weight_pct'] for r in members)<=101:
                raise ValueError('Wind完整指数权重未取得')
            if len(members)!=COUNTS[root]:
                diagnostics['steps'][-1].update(expected=COUNTS[root],actual=len(members))
                raise ValueError('Wind成分数量未匹配指数样本数')
            if dates and dates!={day}:raise ValueError('Wind权重日期不匹配')
            output.setdefault('indices',{})[root]=dict(index_id=index,as_of=day,effective_date=day,
                source='WindPy WSET indexconstituent',industry_standard='申万一级',reviewed_at=stamp,rows=members)
            symbols.update(r['symbol'] for r in members);changed+=1
        except (WindError,ValueError,KeyError,TypeError) as exc:
            warnings.append(w.warning(exc,root+' 权重'))
    missing=sorted(s for s in symbols if not mapping.get(s,{}).get('industry'))
    if missing:
        try:
            industries=wss(w,missing,config.get('industry_field','industry_sw'),
                'tradeDate='+day.replace('-','')+';industryType=1',stop)
            mapping.update({s:dict(industry=str(v).strip(),as_of=day,source='WindPy WSS industry_sw')
                for s,v in industries.items() if isinstance(v,str) and v.strip() and v.strip().lower() not in ('nan','none','--')})
        except (WindError,ValueError,TypeError) as exc:warnings.append(w.warning(exc,'行业'))
    for group in output.get('indices',{}).values():
        for row in group['rows']:row['industry']=mapping.get(row['symbol'],{}).get('industry')
        if group.get('as_of')!=day:continue
        try:
            closes=daily(w,[r['symbol'] for r in group['rows']],'close',day,'PriceAdj=U',stop)
            for row in group['rows']:
                value=number(closes.get(row['symbol']))
                if value is not None and value>0:row.update(anchor_close=value,anchor_date=day)
        except (WindError,ValueError,TypeError) as exc:warnings.append(w.warning(exc,'权重基准收盘'))
    output['industries']=mapping
    if stage=='indices':
        output['errors']=warnings
        if not changed:raise WindError('Wind未返回可发布参考资料')
        return dict(data=output,diagnostics=safe_diagnostics(diagnostics))
    universe=[]
    sectors=[config['etf_sector']] if config.get('etf_sector') else ['股票型ETF','股票型ETF基金','全部ETF基金','ETF基金','全部ETF']
    diagnostics['etf_universe_attempts']=[];diagnostics['tracking_attempts']=[]
    for sector in sectors:
        if stop():raise InterruptedError()
        if any(c in sector for c in ';\r\n'):raise ValueError('ETF板块参数无效')
        try:
            candidates=dataset(w.wset('sectorconstituent',f'date={day};sector={sector}'),'WSET ETF板块')
            universe=[dict(symbol=str(r.get('wind_code','')).upper(),name=str(r.get('sec_name') or '')) for r in candidates]
            universe=[r for r in universe if re.fullmatch(r'(?:5[0-9]{5}\.SH|1[56][0-9]{4}\.SZ)',r['symbol']) and
                      not any(t in r['name'] for t in ('增强','联接','杠杆','反向','FOF'))]
            diagnostics['etf_universe_attempts'].append(dict(sector=sector,candidates=len(universe)))
            if universe:
                diagnostics['etf_sector']=sector;break
        except (WindError,ValueError,TypeError) as exc:
            warnings.append(w.warning(exc,'ETF全集'))
            diagnostics['etf_universe_attempts'].append(dict(sector=sector,error_type=type(exc).__name__,error_code=diagnostics['steps'][-1].get('error_code')));continue
    if universe:
        codes=sorted({r['symbol'] for r in universe});by_code={r['symbol']:r for r in universe};tracking={};resolved=set()
        mapping_complete=False
        for field in ([config['tracking_field']] if config.get('tracking_field') else ['fund_trackindexcode','fund_trackindex']):
            try:
                # Fill only still-unresolved mappings. Different Wind fields may
                # have complementary coverage; neither partial field is a universe.
                values=wss(w,sorted(set(codes)-resolved),field,'tradeDate='+day.replace('-',''),stop)
                for code,value in values.items():
                    if not isinstance(value,str) or value.strip().lower() in ('','none','nan','--','n/a','null','0','无','暂无','不适用'):
                        continue
                    val=str(value).strip().upper();root=next((r for r,i in ROOTS.items() if i==val),None)
                    if root is None:
                        name=str(value).strip();root=NAMES.get(name[:-2] if name.endswith('指数') else name)
                    # A blank/invalid code is unknown, not evidence of an unrelated
                    # benchmark. A real non-target benchmark still resolves scope.
                    if root is None and field=='fund_trackindexcode' and not re.fullmatch(r'[0-9A-Z]{6,12}\.[A-Z]{2,6}',val):continue
                    resolved.add(code)
                    if root:tracking[code]=root
                unresolved=sorted(set(codes)-resolved)
                diagnostics['tracking_attempts'].append(dict(field=field,matching=len(tracking),unresolved=len(unresolved),unresolved_sample=unresolved[:10]))
                if tracking and not unresolved:
                    mapping_complete=True;diagnostics['tracking_field']=field;break
            except (WindError,ValueError,TypeError) as exc:
                warnings.append(w.warning(exc,'ETF标的指数'))
                diagnostics['tracking_attempts'].append(dict(field=field,error_type=type(exc).__name__,error_code=diagnostics['steps'][-1].get('error_code')));continue
        relevant=sorted(tracking)
        if relevant and mapping_complete:
            try:
                field=config.get('aum_field','netasset_total')
                assets=daily(w,relevant,field,day,'unit=1',stop)
                for root,index in ROOTS.items():
                    selected=[s for s in relevant if tracking[s]==root]
                    if not selected or any(number(assets.get(s)) is None or number(assets[s])<=0 for s in selected):
                        warnings.append(root+' ETF完整同日规模未取得');continue
                    output.setdefault('etfs',{})[root]=dict(index_id=index,as_of=day,source='WindPy WSD '+field+';unit=1;Fill=Blank',
                        complete=True,reviewed_at=stamp,as_of_basis='Wind日频Times与请求交易日一致；禁止前值填充',rows=[dict(
                            symbol=s,name=by_code[s]['name'],index_id=index,ordinary_etf=True,aum_date=day,
                            aum_cny=number(assets[s])) for s in selected])
                    changed+=1
                diagnostics['aum_field']=field;diagnostics['aum_unit']='CNY;unit=1'
            except (WindError,ValueError,TypeError) as exc:warnings.append(w.warning(exc,'ETF规模'))
        else:warnings.append('ETF标的指数映射未完整取得；具体字段与失败阶段见诊断')
    else:warnings.append('Wind ETF全集未取得；可在设置中指定终端板块参数')
    output['errors']=warnings
    if not changed:raise WindError('Wind未返回可发布参考资料')
    return dict(data=output,diagnostics=safe_diagnostics(diagnostics))


def main():
    if '--check' in sys.argv:
        import importlib.util
        import site
        try:available=importlib.util.find_spec('WindPy') is not None
        except (ImportError,ValueError):available=False
        print(json.dumps(dict(provider='WindPy',python=sys.executable,module_available=available,
            user_site_enabled=not bool(sys.flags.no_user_site) and bool(site.ENABLE_USER_SITE),connection_attempted=False)))
        return 0
    request=json.loads(sys.stdin.read());result={};w=None
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from WindPy import w
            stop=lambda:bool(request.get('stop_file') and Path(request['stop_file']).exists())
            result=refresh(w,request,stop)
        result['ok']=True
    except Exception as exc:
        result=dict(ok=False,error_type=type(exc).__name__,reason='Wind终端低频查询未完成；查看分阶段错误码，不据此猜测登录、权限或网络原因',
                    diagnostics=safe_diagnostics(getattr(exc,'diagnostics',dict(provider='WindPy',requested_day=request.get('day'),
                        steps=[dict(stage='import' if w is None else 'worker',status='failed',error_type=type(exc).__name__)]))))
    finally:
        if w is not None:
            try:
                with contextlib.redirect_stdout(sys.stderr):w.stop()
            except Exception:pass  # Cleanup must not erase the original error evidence.
    print(json.dumps(result,ensure_ascii=False,allow_nan=False,default=lambda v:v.isoformat() if hasattr(v,'isoformat') else str(v)))
    return 0


if __name__=='__main__':raise SystemExit(main())
