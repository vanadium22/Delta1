"""Read existing immutable publications or the supplied research archive. Never network."""
from datetime import date,timedelta,datetime
import hashlib,json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/'outputs/2026-10-23/股指期货指标_前端实现规范_第六版_2026-10-23.json'
SPOTS={'IF':'000300.SH','IH':'000016.SH','IC':'000905.SH','IM':'000852.SH'}


def dates_between(first,last):
    from dashboard.marketdata.trading_calendar import HOLIDAYS
    result=[];d=date.fromisoformat(first);end=date.fromisoformat(last)
    while d<=end:
        if d.year not in HOLIDAYS:raise ValueError('该年份缺已验证交易日历，不能猜测交易日')
        if d.weekday()<5 and not any(a<=d.strftime('%m-%d')<=b for a,b in HOLIDAYS[d.year]):result.append(d.isoformat())
        d+=timedelta(days=1)
    return result


class Archive:
    mode='replay'
    def __init__(self):
        self.spec=json.loads(SPEC.read_text(encoding='utf8')) if SPEC.exists() else None
        self.manifest=ROOT/'data/ddb_basis_v3/20261015T072149_7c439ee5/run.json'
        self.raw={};self.contracts={};self.minute_cache={}
        self.source='研究回放 · 已有 Wind 日频 / CSMAR 分钟归档'
        self.version=hashlib.sha256(SPEC.read_bytes()).hexdigest() if self.spec else 'unavailable'
        self.selections=self.spec['datasets']['daily'] if self.spec else []
        self.days=[r['trading_date'] for r in self.selections]
        self.files=[]
        if self.manifest.exists():
            self.version=hashlib.sha256((self.version+hashlib.sha256(self.manifest.read_bytes()).hexdigest()).encode()).hexdigest()
            self.files=json.loads(self.manifest.read_text(encoding='utf8'))['files']
            for item in self.files:
                name=Path(item['file']).name
                if name not in ('contract_reference.parquet','daily_futures.parquet','daily_indices.parquet'):continue
                frame=self.read(item)
                if name=='contract_reference.parquet':
                    for r in frame.sort_values('OPDATE').drop_duplicates('S_INFO_WINDCODE',keep='last').to_dict('records'):
                        self.contracts[r['S_INFO_WINDCODE']]=dict(listing=str(r['S_INFO_LISTDATE'].date()),expiry=str(r['S_INFO_DELISTDATE'].date()),multiplier=300 if r['S_INFO_WINDCODE'].startswith(('IF','IH')) else 200)
                else:
                    for r in frame.to_dict('records'):self.raw[(r['source_symbol'],str(r['trading_date'].date()))]=r
            if self.raw:self.days=dates_between(min(d for s,d in self.raw),max(d for s,d in self.raw))
        self.available=bool(self.spec)

    def read(self,item):
        # Relocatable manifest: no developer-drive dependency on company machines.
        path=self.manifest.parent/Path(item['file']).name
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('归档校验失败：'+path.name)
        return pd.read_parquet(path)

    def minutes(self,day,far,near):
        key=(day,far,near)
        if key in self.minute_cache:return self.minute_cache[key]
        data={}
        if self.files:
            month=day[:7]
            for item in self.files:
                name=Path(item['file']).name
                if item.get('kind')!='normalized' or not name.startswith('minute_') or month not in name:continue
                df=self.read(item);df=df[pd.to_datetime(df.trading_date).dt.strftime('%Y-%m-%d')==day]
                for r in df.to_dict('records'):
                    symbol=r['source_symbol'];role='F' if symbol==far else 'N' if symbol==near else 'S' if symbol==SPOTS.get(far[:2]) else None
                    if role:
                        stamp=pd.Timestamp(r['timestamp']).strftime('%Y-%m-%dT%H:%M:%S')+'+08:00'
                        row=data.setdefault(stamp,{});row[role]=r.get('close')
                        if role in ('F','N'):row['V' if role=='F' else 'VN']=r.get('volume')
        if not data and self.spec and day==self.spec['datasets']['metadata']['minute_day'] and far=='IF2612.CFE' and near=='IF2610.CFE':
            data={r['timestamp']:r['raw'] for r in self.spec['datasets']['minute']}
        self.minute_cache[key]=data
        return data


class Published:
    mode='published'
    def __init__(self,config):
        from dashboard.marketdata.repository import MarketDataRepository,ReferenceBook
        from dashboard.marketdata.history_publication import maintenance_root
        roots=config.get('history_roots',[])
        if not roots:raise ValueError('尚未配置已发布历史数据；可选择研究回放')
        self.repo=MarketDataRepository(roots,allow_unverified=config.get('allow_unverified',False),publication=maintenance_root(roots)/'publication.json')
        self.frozen=self.repo.freeze();self.reference=ReferenceBook(config.get('reference_file'))
        self.version=hashlib.sha256(json.dumps(self.frozen,sort_keys=True,default=str).encode()).hexdigest()
        self.source='现有数据服务 · 已发布完整观测（非实时行情）';self.raw={};self.contracts={};self.minute_cache={};self.spec=None
        self.asof=pd.Timestamp.now(tz='Asia/Shanghai')
        self.sessions=config.get('indicator_v6_sessions')
        supported={(p['instrument_id'],p['frequency']) for snap in self.frozen.values() for p in snap['parts']}
        self.supported=supported
        for symbol in self.repo.symbols(self.frozen):
            if symbol[:2] in SPOTS:
                meta=self.reference.contract(symbol,self.asof)
                if meta:self.contracts[symbol]=dict(listing=meta['listing_date'],expiry=meta['expiry_date'],multiplier=meta.get('multiplier',300 if symbol.startswith(('IF','IH')) else 200))
            if (symbol,'1d') not in supported:continue
            df=self.repo.read_window(symbol,'1d',count=800,as_of=self.asof,fields=('open','high','low','close','volume','open_interest'),frozen=self.frozen)
            for r in df.to_dict('records'):
                if not r.get('is_final'):continue
                stamp=pd.Timestamp(r['event_time']).tz_convert('Asia/Shanghai')
                if stamp.date()>=self.asof.date():continue
                r['oi']=r.get('open_interest');self.raw[(symbol,str(stamp.date()))]=r
        if not self.raw:raise ValueError('现有数据服务没有可读取的已完成日频观测')
        self.days=dates_between(min(d for s,d in self.raw),max(d for s,d in self.raw));self.available=True;self.selections=[]
        for day in self.days:
            fs=sorted((r['expiry'],s) for s,r in self.contracts.items() if s.startswith('IF') and r['listing']<=day and (date.fromisoformat(r['expiry'])-date.fromisoformat(day)).days>=60)
            if not fs:continue
            expiry,far=fs[0]
            ns=sorted((r['expiry'],s) for s,r in self.contracts.items() if s.startswith('IF') and r['listing']<=day and day<=r['expiry']<expiry and (date.fromisoformat(r['expiry'])-date.fromisoformat(day)).days>=7)
            cross=next((s for s,r in self.contracts.items() if s.startswith('IC') and r['expiry']==expiry and r['listing']<=day),None)
            self.selections.append(dict(trading_date=day,far=far,near=ns[0][1] if ns else None,cross=cross))
        self.version=hashlib.sha256(json.dumps([self.frozen,self.contracts,self.sessions,config.get('allow_unverified',False)],sort_keys=True,default=str).encode()).hexdigest()

    def minutes(self,day,far,near):
        key=(day,far,near)
        if key in self.minute_cache:return self.minute_cache[key]
        data={};cutoff=pd.Timestamp(day+'T15:00:00+08:00')
        for symbol,role in [(far,'F'),(near,'N'),(SPOTS.get(far[:2]),'S')]:
            if not symbol or (symbol,'1m') not in self.supported:continue
            df=self.repo.read_window(symbol,'1m',count=1200,as_of=cutoff,fields=('close','volume'),frozen=self.frozen)
            for r in df.to_dict('records'):
                stamp=pd.Timestamp(r['event_time']).tz_convert('Asia/Shanghai')
                if str(stamp.date())!=day or not r.get('is_final'):continue
                row=data.setdefault(stamp.isoformat(),{});row[role]=r.get('close')
                if role in ('F','N'):row['V' if role=='F' else 'VN']=r.get('volume')
        self.minute_cache[key]=data;return data
