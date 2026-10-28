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
PROTOCOL='wind-terminal-v5-membership-and-nav'
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
    'Wind权重日期未完整取得':'weight_date_unverified',
    'WindETF全集日期不匹配':'universe_date_mismatch',
    'WindETF全集日期未完整取得':'universe_date_unverified',
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
    for key in ('provider','protocol','python','requested_day','stage','tracking_field','aum_field','aum_unit','etf_sector'):
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
            for key in ('stage','operation','dataset','status','root','index_id','field','sector','day','date_argument','times_basis','matrix_layout','started_at','finished_at','error_type','reason_code'):
                item=row.get(key)
                if isinstance(item,str) and len(item)<=128 and re.fullmatch(r'[\w .:+/\-()\u4e00-\u9fff]+',item):entry[key]=item
            for key in ('error_code','codes_count','returned_codes_count','batch','candidates','matching','unresolved','expected','actual',
                        'matrix_rows','row_count','row_date_distinct_count','missing_row_date_count','invalid_row_date_count',
                        'missing_weight_count','invalid_weight_count','negative_weight_count','invalid_code_count','duplicate_code_count'):
                item=error_code(row.get(key))
                if item is not None:entry[key]=item
            for key in ('connected_before','connected_after'):
                if key in row and (row[key] is None or isinstance(row[key],bool)):entry[key]=row[key]
            for key in ('returned_fields','requested_fields'):
                fields=row.get(key)
                if isinstance(fields,list):entry[key]=[s for s in fields[:30] if isinstance(s,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',s)]
            for key in ('returned_dates','returned_row_dates'):
                dates=row.get(key)
                if isinstance(dates,list):entry[key]=[s for s in dates[:5] if isinstance(s,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',s)]
            lengths=row.get('matrix_row_lengths')
            if isinstance(lengths,list):entry['matrix_row_lengths']=[s for s in lengths[:20] if isinstance(s,int) and not isinstance(s,bool) and -1<=s<=1000000]
            total=number(row.get('weight_total'))
            if total is not None:entry['weight_total']=total
            sample=row.get('unresolved_sample')
            if isinstance(sample,list):entry['unresolved_sample']=[s for s in sample[:10] if isinstance(s,str) and SECURITY.fullmatch(s)]
            safe.append(entry)
        output[name]=safe
    return output


class TrackedWind:
    """Record low-frequency call context before invoking the existing terminal."""
    def __init__(self,w,request):
        self.w=w;self.request=request
        self.diagnostics=dict(provider='WindPy',protocol=PROTOCOL,python=sys.executable,user_site_enabled=not bool(sys.flags.no_user_site),
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
            matrix=getattr(result,'Data',None)
            if isinstance(matrix,(list,tuple)):
                entry.update(matrix_rows=len(matrix),matrix_row_lengths=[len(r) if isinstance(r,(list,tuple)) else -1 for r in matrix[:20]])
            codes=getattr(result,'Codes',None)
            if isinstance(codes,(list,tuple)):entry['returned_codes_count']=len(codes)
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
        context=dict(stage='index_weights' if kind=='indexconstituent' else 'etf_universe',dataset=kind,
            date_argument=parts.get('date'),requested_fields=parts.get('field','').split(','),times_basis='query_metadata_not_row_dates')
        if kind=='indexconstituent':context.update(index_id=parts.get('windcode'),root=next((r for r,c in ROOTS.items() if c==parts.get('windcode')),None))
        else:context['sector']=parts.get('sector')
        return self.call('wset',(kind,options),**context)
    def wss(self,codes,field,options):
        return self.call('wss',(codes,field,options),stage='industry' if field==self.request.get('config',{}).get('industry_field','industry_sw') else 'etf_tracking',field=field,codes_count=len(codes.split(',')))
    def wsd(self,codes,field,start,end,options):
        etf_codes=all(re.fullmatch(r'(?:5[0-9]{5}\.SH|1[56][0-9]{4}\.SZ)',c) for c in codes.split(','))
        stage='etf_nav' if field=='nav' else 'etf_close' if field=='close' and etf_codes else 'anchor_close' if field=='close' else 'etf_scale'
        return self.call('wsd',(codes,field,start,end,options),stage=stage,field=field,codes_count=len(codes.split(',')))

    def warning(self,exc,label):
        entry=self.diagnostics['steps'][-1]
        if entry.get('status')!='failed':
            entry.update(status='invalid_response',reason_code=VALIDATION_CODES.get(str(exc),'response_validation'),error_type=type(exc).__name__)
            self.diagnostics['failures'].append(dict(entry))
        self.checkpoint()
        # These are application labels, not str(exc) or Wind Data/connection text.
        return label+'：'+('样本数不匹配，' if entry.get('expected') is not None and entry.get('expected')!=entry.get('actual') else '')+entry['stage']+'，'+entry.get('reason_code','response_validation')


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


def evidence(w,**values):
    if isinstance(w,TrackedWind):
        w.diagnostics['steps'][-1].update(values);w.checkpoint()


def dataset_dates(w,rows):
    """WSET Times is query metadata; verify the date column of every row."""
    dates=set();missing=invalid=0
    for row in rows:
        value=row.get('date')
        if value is None or str(value).strip()=='':missing+=1;continue
        try:dates.add(iso(value))
        except (TypeError,ValueError):invalid+=1
    evidence(w,row_count=len(rows),returned_row_dates=sorted(dates)[:5],row_date_distinct_count=len(dates),
        missing_row_date_count=missing,invalid_row_date_count=invalid)
    return dates,missing,invalid


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
        if [iso(t) for t in value.Times]!=[day] or set(returned)!=set(batch) or len(returned)!=len(batch) or len(set(returned))!=len(returned):
            raise ValueError('Wind日频日期或代码不匹配')
        if ([str(f).lower() for f in value.Fields]!=[field.lower()] or
            not isinstance(value.Data,(list,tuple)) or any(not isinstance(row,(list,tuple)) for row in value.Data)):
            raise ValueError('Wind单日日频矩阵不匹配')
        # WindQuant/Official WindPy.py: WindData.set's timeL==1 branch is
        # field-major, even with multiple codes. Retain the unambiguous N x 1
        # layout too; never flatten an arbitrary matrix or reorder by request.
        if len(value.Data)==1 and len(value.Data[0])==len(returned):
            values=value.Data[0];layout='single_field_by_code'
        elif len(value.Data)==len(returned) and all(len(v)==1 for v in value.Data):
            values=[v[0] for v in value.Data];layout='code_by_single_date'
        else:raise ValueError('Wind单日日频矩阵不匹配')
        evidence(w,matrix_layout=layout)
        result.update(zip(returned,values))
    return result


def refresh(w,request,stop=lambda:False):
    tracked=TrackedWind(w,request)
    try:return _refresh(tracked,request,stop)
    except Exception as exc:
        if isinstance(exc,InterruptedError):error=exc
        else:error=WindError('Wind低频资料未完成；查看安全分阶段诊断')
        error.diagnostics=safe_diagnostics(tracked.diagnostics)
        raise error from None


def refresh_nav(w,output,day,stamp,stop,warnings):
    """Dated close/NAV only. These values never become intraday IOPV."""
    codes=sorted({r['symbol'] for group in output.get('etfs',{}).values() if group.get('complete') is True
        for r in sorted(group.get('rows',[]),key=lambda r:(-r['aum_cny'],r['symbol']))[:3]})
    if not codes:return 0
    try:
        nav=daily(w,codes,'nav',day,'unit=1',stop)
        closes=daily(w,codes,'close',day,'PriceAdj=U',stop)
        rows={s:r for s,r in output.get('etf_nav',{}).get('rows',{}).items() if s in codes};updated=0
        for symbol in codes:
            n,c=number(nav.get(symbol)),number(closes.get(symbol))
            if n is not None and n>0 and c is not None and c>0:
                rows[symbol]=dict(symbol=symbol,as_of=day,nav_cny=n,close_cny=c,
                    source='WindPy WSD nav / unadjusted close; Fill=Blank',fetched_at=stamp);updated+=1
        output['etf_nav']=dict(schema='etf-nav-v1',requested_day=day,fetched_at=stamp,rows=rows)
        if updated!=len(codes):warnings.append('ETF同日净值/收盘未齐，保留原日期，不替代IOPV')
        return updated
    except (WindError,ValueError,TypeError) as exc:
        warnings.append(w.warning(exc,'ETF收盘净值'));return 0


def _refresh(w,request,stop):
    checked(w.start(waitTime=10,showmenu=False),'Wind连接')
    old=request.get('old') or {};config=request.get('config') or {}
    day=request['day'];stamp=request['fetched_at'];warnings=[]
    output=deepcopy(old) if old else dict(schema='overview-reference-v1',indices={},etfs={})
    output['fetched_at']=stamp;mapping=deepcopy(old.get('industries',{}));symbols=set();changed=0
    diagnostics=w.diagnostics;stage=request.get('stage','all')
    if stage not in ('all','connect','indices','etfs','nav'):raise ValueError('低频检查阶段无效')
    if stage=='connect':return dict(data=output,diagnostics=safe_diagnostics(diagnostics))
    if stage=='nav':
        if not refresh_nav(w,output,day,stamp,stop,warnings):raise WindError('Wind未返回可发布参考资料')
        output['errors']=[s for s in old.get('errors',[]) if not s.startswith(('ETF同日净值','ETF收盘净值'))]+warnings
        return dict(data=output,diagnostics=safe_diagnostics(diagnostics))
    output['reference_reviewed_at']=stamp
    for root,index in (ROOTS.items() if stage in ('all','indices') else []):
        if stop():raise InterruptedError()
        try:
            rows=dataset(w.wset('indexconstituent',f'date={day.replace("-","")};windcode={index};field=date,wind_code,sec_name,i_weight'),'WSET indexconstituent')
            dates,missing_dates,invalid_dates=dataset_dates(w,rows)
            codes=[str(r.get('wind_code','')).upper() for r in rows];weights=[number(r.get('i_weight')) for r in rows]
            missing_weights=sum(r.get('i_weight') is None or str(r.get('i_weight')).strip().lower() in ('','nan','none','--','null','n/a') for r in rows)
            evidence(w,expected=COUNTS[root],actual=len(rows),missing_weight_count=missing_weights,
                invalid_weight_count=sum(v is None for v in weights)-missing_weights,negative_weight_count=sum(v is not None and v<0 for v in weights),
                invalid_code_count=sum(not SECURITY.fullmatch(c) for c in codes),duplicate_code_count=len(codes)-len(set(codes)),
                weight_total=sum(v for v in weights if v is not None))
            members=[]
            for row,code,weight in zip(rows,codes,weights):
                if not SECURITY.fullmatch(code):raise ValueError('Wind成分权重无效')
                try:reference_date=iso(row['date'])
                except (KeyError,ValueError,TypeError):reference_date=None
                members.append(dict(symbol=code,name=str(row.get('sec_name') or code),
                    weight_pct=weight if weight is not None and 0<=weight<=100 else None,
                    reference_date=reference_date,industry=None))
            if not members or len({r['symbol'] for r in members})!=len(members):raise ValueError('Wind完整指数权重未取得')
            if len(members)!=COUNTS[root]:
                diagnostics['steps'][-1].update(expected=COUNTS[root],actual=len(members))
                raise ValueError('Wind成分数量未匹配指数样本数')
            complete=(not missing_dates and not invalid_dates and len(dates)==1 and max(dates)<=day and
                all(r['weight_pct'] is not None for r in members) and 99<=sum(r['weight_pct'] for r in members)<=101)
            as_of=next(iter(dates)) if complete else day
            if not complete:
                reason='Wind成分权重无效' if any(r['weight_pct'] is None for r in members) else 'Wind权重日期未完整取得' if missing_dates or invalid_dates else 'Wind权重日期不匹配'
                warnings.append(w.warning(ValueError(reason),root+' 权重未完整核验，成分名单保留'))
            output.setdefault('indices',{})[root]=dict(index_id=index,as_of=as_of,effective_date=day,
                source='WindPy WSET indexconstituent',industry_standard='申万一级',reviewed_at=stamp,rows=members)
            output['indices'][root].update(membership_complete=True,membership_as_of=day,
                membership_date_basis='Wind indexconstituent requested day; row reference dates retained separately',
                weights_complete=complete,weight_as_of=as_of if complete else None,
                weight_method='source_reference' if complete else 'incomplete_reference',weight_source_dates=sorted(dates),
                weight_reason=None if complete else '参考日期混合或权重缺失；保留成分名单，不归一化、不补零、不计算未核验贡献')
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
            candidates=dataset(w.wset('sectorconstituent',f'date={day.replace("-","")};sector={sector};field=date,wind_code,sec_name'),'WSET ETF板块')
            dates,missing_dates,invalid_dates=dataset_dates(w,candidates)
            if missing_dates or invalid_dates or not dates:raise ValueError('WindETF全集日期未完整取得')
            if dates!={day}:raise ValueError('WindETF全集日期不匹配')
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
    refresh_nav(w,output,day,stamp,stop,warnings)
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
