"""Standard-library-only, read-only WindPy reference worker. Never WSQ/WSI or VPN.

Run in the user's existing Wind Python WITHOUT -s: WindPy is often registered
in the user site. No pandas, Qt, Oracle driver, installs or database credentials.
"""
from copy import deepcopy
from datetime import date, datetime
import contextlib
import json
import math
import re
import sys

ROOTS={'IF':'000300.SH','IH':'000016.SH','IC':'000905.SH','IM':'000852.SH'}
COUNTS={'IF':300,'IH':50,'IC':500,'IM':1000}
NAMES={'沪深300':'IF','上证50':'IH','中证500':'IC','中证1000':'IM'}
SECURITY=re.compile(r'[0-9]{6}\.(?:SH|SZ)')


class WindError(Exception):
    pass


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
    checked(w.start(waitTime=10,showmenu=False),'Wind连接')
    old=request.get('old') or {};config=request.get('config') or {}
    day=request['day'];stamp=request['fetched_at'];warnings=[]
    output=deepcopy(old) if old else dict(schema='overview-reference-v1',indices={},etfs={})
    output['fetched_at']=stamp;mapping=deepcopy(old.get('industries',{}));symbols=set();changed=0
    diagnostics=dict(provider='WindPy',python=sys.executable,user_site_enabled=not bool(sys.flags.no_user_site),
                     requested_day=day,operations=['WSET','WSS','WSD(single completed day, no fill)'],groups=[])
    for root,index in ROOTS.items():
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
            if len(members)!=COUNTS[root]:raise ValueError('Wind成分数量未匹配指数样本数：'+str(len(members))+'/'+str(COUNTS[root]))
            if dates and dates!={day}:raise ValueError('Wind权重日期不匹配')
            output.setdefault('indices',{})[root]=dict(index_id=index,as_of=day,effective_date=day,
                source='WindPy WSET indexconstituent',industry_standard='申万一级',reviewed_at=stamp,rows=members)
            symbols.update(r['symbol'] for r in members);changed+=1
        except (WindError,ValueError,KeyError,TypeError) as exc:
            warnings.append(root+' 权重：'+str(exc))
    missing=sorted(s for s in symbols if not mapping.get(s,{}).get('industry'))
    if missing:
        try:
            industries=wss(w,missing,config.get('industry_field','industry_sw'),
                'tradeDate='+day.replace('-','')+';industryType=1',stop)
            mapping.update({s:dict(industry=str(v).strip(),as_of=day,source='WindPy WSS industry_sw')
                for s,v in industries.items() if isinstance(v,str) and v.strip() and v.strip().lower() not in ('nan','none','--')})
        except (WindError,ValueError,TypeError) as exc:warnings.append('行业：'+str(exc))
    for group in output.get('indices',{}).values():
        for row in group['rows']:row['industry']=mapping.get(row['symbol'],{}).get('industry')
        if group.get('as_of')!=day:continue
        try:
            closes=daily(w,[r['symbol'] for r in group['rows']],'close',day,'PriceAdj=U',stop)
            for row in group['rows']:
                value=number(closes.get(row['symbol']))
                if value is not None and value>0:row.update(anchor_close=value,anchor_date=day)
        except (WindError,ValueError,TypeError) as exc:warnings.append('权重基准收盘：'+str(exc))
    output['industries']=mapping
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
            diagnostics['etf_universe_attempts'].append(dict(sector=sector,error_type=type(exc).__name__,reason=str(exc)));continue
    if universe:
        codes=sorted({r['symbol'] for r in universe});by_code={r['symbol']:r for r in universe};tracking={}
        mapping_complete=False
        for field in ([config['tracking_field']] if config.get('tracking_field') else ['fund_trackindexcode','fund_trackindex']):
            try:
                values=wss(w,codes,field,'tradeDate='+day.replace('-',''),stop)
                candidate={};unresolved=[]
                for code,value in values.items():
                    if value is None or str(value).strip().lower() in ('','none','nan','--','n/a'):
                        unresolved.append(code);continue
                    val=str(value).strip().upper();root=next((r for r,i in ROOTS.items() if i==val),None)
                    if root is None:
                        name=str(value).strip();root=NAMES.get(name[:-2] if name.endswith('指数') else name)
                    if root:candidate[code]=root
                if candidate and not unresolved:
                    tracking=candidate;mapping_complete=True;diagnostics['tracking_field']=field;break
                diagnostics['tracking_attempts'].append(dict(field=field,matching=len(candidate),unresolved=len(unresolved),unresolved_sample=unresolved[:10]))
            except (WindError,ValueError,TypeError) as exc:
                diagnostics['tracking_attempts'].append(dict(field=field,error_type=type(exc).__name__,reason=str(exc)));continue
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
            except (WindError,ValueError,TypeError) as exc:warnings.append('ETF规模：'+str(exc))
        else:warnings.append('ETF标的指数映射未取得；请核对Wind字段权限')
    else:warnings.append('Wind ETF全集未取得；可在设置中指定终端板块参数')
    output['errors']=warnings;diagnostics['groups']=warnings
    if not changed:raise WindError('Wind未返回可发布参考资料')
    return dict(data=output,diagnostics=diagnostics)


def main():
    if '--check' in sys.argv:
        import importlib.util
        import site
        try:available=importlib.util.find_spec('WindPy') is not None
        except (ImportError,ValueError):available=False
        print(json.dumps(dict(provider='WindPy',python=sys.executable,module_available=available,
            user_site_enabled=not bool(sys.flags.no_user_site) and bool(site.ENABLE_USER_SITE),connection_attempted=False)))
        return 0
    request=json.loads(sys.stdin.read());result={}
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from WindPy import w
            try:
                from pathlib import Path
                stop=lambda:bool(request.get('stop_file') and Path(request['stop_file']).exists())
                result=refresh(w,request,stop)
            finally:
                w.stop()
        result['ok']=True
    except Exception as exc:
        result=dict(ok=False,error_type=type(exc).__name__,reason=str(exc) if isinstance(exc,(WindError,ValueError)) else 'Wind终端参考查询未完成')
    print(json.dumps(result,ensure_ascii=False,allow_nan=False,default=lambda v:v.isoformat() if hasattr(v,'isoformat') else str(v)))
    return 0


if __name__=='__main__':raise SystemExit(main())
