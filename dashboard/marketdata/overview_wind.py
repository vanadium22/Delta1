"""Bounded, low-frequency Wind database reference reads. Never quotes or VPN.

Each query first checks the visible schema. Unknown fields/asset units fail
closed and are reported, rather than publishing an invented size ranking.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import importlib
import os
from pathlib import Path
import re
import sys

from .overview_reference import ROOTS, SCHEMA, finite

TABLES = ('AINDEXHS300FREEWEIGHT', 'AINDEXHS300WEIGHT', 'ASHAREDESCRIPTION',
          'ASHARESWNINDUSTRIESCLASS', 'ASHARESWINDUSTRIESCLASS', 'ASHAREINDUSTRIESCODE',
          'CHINAMUTUALFUNDTRACKINGINDEX', 'CHINAETFINVESTCLASS', 'CHINAMUTUALFUNDNAV')
INDUSTRIES = set('农林牧渔 基础化工 化工 钢铁 有色金属 电子 汽车 家用电器 食品饮料 纺织服饰 纺织服装 轻工制造 医药生物 公用事业 交通运输 房地产 商贸零售 商业贸易 社会服务 休闲服务 综合 建筑材料 建筑装饰 电力设备 电气设备 国防军工 计算机 传媒 通信 银行 非银金融 煤炭 采掘 石油石化 环保 美容护理 机械设备'.split())


def settings_path(config, local_root):
    if os.environ.get('WIND_DB_CONFIG'):
        return Path(os.environ['WIND_DB_CONFIG'])
    if config.get('overview_wind_config'):
        return Path(config['overview_wind_config'])
    root = Path(local_root).resolve()
    choices = [root/'wind_db.json', root.parent.parent/'localsetting/wind_db.json',
               Path(__file__).resolve().parents[2]/'localsetting/wind_db.json']
    return next((p for p in choices if p.is_file()), choices[0])


def connect(config, local_root):
    # Reuse user-owned Oracle settings. No credential copies, installations,
    # permanent environment changes, or raw driver errors in the UI/report.
    try:
        import oracledb
    except ImportError:
        root = Path(local_root).resolve()
        candidates = [root.parent.parent/'index_strategy/data_dld/.deps',
                      Path(__file__).resolve().parents[2]/'index_strategy/data_dld/.deps']
        for candidate in candidates:
            if (candidate/'oracledb').is_dir():
                sys.path.insert(0, str(candidate)); break
        oracledb = importlib.import_module('oracledb')
    from index_strategy.data_dld.wind_connection import credentials
    if os.environ.get('ORACLE_CLIENT_LIB_DIR'):
        oracledb.init_oracle_client(lib_dir=os.environ['ORACLE_CLIENT_LIB_DIR'])
    conf = credentials(settings_path(config, local_root))
    params = oracledb.ConnectParams()
    params.parse_connect_string(conf.pop('dsn'))
    params.set(tcp_connect_timeout=8, retry_count=0)
    db = oracledb.connect(**conf, dsn=params.get_connect_string())
    db.call_timeout = 15000
    return db


class WindReferences:
    def __init__(self, db, config, stop=lambda: False):
        from index_strategy.data_dld.wind_connection import select
        self.db, self.config, self.stop, self.select = db, config, stop, select
        binds = {f't{i}': t for i, t in enumerate(TABLES)}
        names = ','.join(':'+k for k in binds)
        rows = self.read("SELECT TABLE_NAME,COLUMN_NAME FROM ALL_TAB_COLUMNS WHERE OWNER='WIND' AND TABLE_NAME IN ("+names+")", binds, 1000)
        self.columns = {t: {r['COLUMN_NAME'] for r in rows if r['TABLE_NAME'] == t} for t in TABLES}
        try:
            comments = self.read("SELECT TABLE_NAME,COLUMN_NAME,COMMENTS FROM ALL_COL_COMMENTS WHERE OWNER='WIND' AND TABLE_NAME IN ("+names+")", binds, 1000)
        except InterruptedError:
            raise
        except Exception:
            comments = []
        self.comments = {(r['TABLE_NAME'], r['COLUMN_NAME']): str(r.get('COMMENTS') or '') for r in comments}

    def read(self, sql, binds=None, limit=3000):
        if self.stop():
            raise InterruptedError('资料任务已取消')
        return self.select(self.db, sql, binds, limit=limit)

    def has(self, table, *columns):
        return set(columns).issubset(self.columns.get(table, set()))

    def weights(self, root, cutoff):
        for table in ('AINDEXHS300FREEWEIGHT', 'AINDEXHS300WEIGHT'):
            if not self.has(table, 'S_INFO_WINDCODE', 'S_CON_WINDCODE', 'TRADE_DT', 'I_WEIGHT'):
                continue
            rows = self.read(f'SELECT S_CON_WINDCODE,TRADE_DT,I_WEIGHT FROM WIND.{table} '
                f'WHERE S_INFO_WINDCODE=:code AND TRADE_DT=(SELECT MAX(TRADE_DT) FROM WIND.{table} '
                'WHERE S_INFO_WINDCODE=:code AND TRADE_DT<=:cutoff) AND ROWNUM<=3001',
                dict(code=ROOTS[root], cutoff=cutoff))
            if rows:
                as_of = self.date(rows[0]['TRADE_DT'])
                return dict(index_id=ROOTS[root], as_of=as_of, effective_date=as_of,
                    source='Wind.'+table, industry_standard='申万一级（Wind分类）',
                    rows=[dict(symbol=r['S_CON_WINDCODE'], name=r['S_CON_WINDCODE'],
                               weight_pct=float(r['I_WEIGHT']), industry=None) for r in rows])
        raise ValueError('未取得完整指数权重；保留旧资料')

    @staticmethod
    def date(value):
        text = str(value)[:10].replace('-', '')
        return datetime.strptime(text[:8], '%Y%m%d').date().isoformat()

    def classify(self, symbols, cutoff):
        result = {}
        table = next((t for t in ('ASHARESWNINDUSTRIESCLASS', 'ASHARESWINDUSTRIESCLASS') if
                      self.has(t, 'S_INFO_WINDCODE', 'SW_IND_CODE', 'ENTRY_DT', 'REMOVE_DT')), None)
        if not table or not self.has('ASHAREINDUSTRIESCODE', 'INDUSTRIESCODE', 'INDUSTRIESNAME', 'LEVELNUM'):
            return result
        for offset in range(0, len(symbols), 250):
            binds = {f'c{i}': s for i, s in enumerate(symbols[offset:offset+250])}
            codes = ','.join(':'+k for k in binds)
            binds['cutoff'] = cutoff
            rows = self.read(f'SELECT C.S_INFO_WINDCODE,D.INDUSTRIESNAME FROM WIND.{table} C '
                'JOIN WIND.ASHAREINDUSTRIESCODE D ON SUBSTR(C.SW_IND_CODE,1,4)=SUBSTR(D.INDUSTRIESCODE,1,4) '
                f'WHERE C.S_INFO_WINDCODE IN ({codes}) AND D.LEVELNUM=2 '
                'AND C.ENTRY_DT<=:cutoff AND (C.REMOVE_DT IS NULL OR C.REMOVE_DT>:cutoff)', binds)
            # Unknown taxonomies, duplicate mappings or non-first-level names
            # remain unclassified. Never make an industry up from a ticker.
            by_symbol = {}
            for r in rows:
                by_symbol.setdefault(r['S_INFO_WINDCODE'], set()).add(r['INDUSTRIESNAME'])
            for s, names in by_symbol.items():
                if len(names) == 1 and next(iter(names)) in INDUSTRIES:
                    result[s] = dict(industry=next(iter(names)), as_of=self.date(cutoff), source='Wind.'+table)
        return result

    def names(self, symbols):
        result = {}
        if not self.has('ASHAREDESCRIPTION', 'S_INFO_WINDCODE', 'S_INFO_NAME'):
            return result
        for offset in range(0, len(symbols), 250):
            binds = {f'c{i}': s for i, s in enumerate(symbols[offset:offset+250])}
            rows = self.read('SELECT S_INFO_WINDCODE,S_INFO_NAME FROM WIND.ASHAREDESCRIPTION '
                             'WHERE S_INFO_WINDCODE IN ('+','.join(':'+k for k in binds)+')', binds)
            result.update({r['S_INFO_WINDCODE']: r['S_INFO_NAME'] for r in rows})
        return result

    def funds(self, root, cutoff):
        if not self.has('CHINAMUTUALFUNDTRACKINGINDEX', 'S_INFO_WINDCODE', 'S_INFO_INDEXWINDCODE', 'ENTRY_DT', 'REMOVE_DT') or not self.has('CHINAETFINVESTCLASS', 'S_INFO_WINDCODE', 'S_INFO_NAME'):
            raise ValueError('ETF范围及对应指数字段待核验')
        rows = self.read('SELECT DISTINCT T.S_INFO_WINDCODE,C.S_INFO_NAME FROM WIND.CHINAMUTUALFUNDTRACKINGINDEX T '
            'JOIN WIND.CHINAETFINVESTCLASS C ON C.S_INFO_WINDCODE=T.S_INFO_WINDCODE '
            'WHERE T.S_INFO_INDEXWINDCODE=:code AND T.ENTRY_DT<=:cutoff '
            'AND (T.REMOVE_DT IS NULL OR T.REMOVE_DT>:cutoff) AND ROWNUM<=301', dict(code=ROOTS[root], cutoff=cutoff), 300)
        candidates = {r['S_INFO_WINDCODE']: r['S_INFO_NAME'] for r in rows if
            re.fullmatch(r'(?:5[0-9]{5}\.SH|1[56][0-9]{4}\.SZ)', r['S_INFO_WINDCODE']) and
            not any(word in str(r['S_INFO_NAME']) for word in ('增强', '联接', '杠杆', '反向', 'FOF'))}
        if not candidates:
            raise ValueError('同指数普通ETF范围待核验')
        field = self.config.get('overview_wind_aum_field', 'F_NAV_TOTAL')
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,40}', field) or not self.has('CHINAMUTUALFUNDNAV', 'S_INFO_WINDCODE', 'PRICE_DATE', field):
            raise ValueError('基金净资产字段待核验')
        comment = self.comments.get(('CHINAMUTUALFUNDNAV', field), '')
        multiplier = self.config.get('overview_wind_aum_multiplier')
        if multiplier is None:
            if '万元' in comment: multiplier = 10000
            elif '亿元' in comment: multiplier = 100000000
            elif '元' in comment and ('净资产' in comment or '资产净值' in comment): multiplier = 1
        if not finite(multiplier) or multiplier <= 0:
            raise ValueError('基金净资产人民币单位待核验；不猜规模')
        binds = {f'c{i}': s for i, s in enumerate(candidates)}
        codes = ','.join(':'+k for k in binds); binds['cutoff'] = cutoff
        # A common exact date is required across the entire candidate universe.
        dates = self.read(f'SELECT PRICE_DATE FROM WIND.CHINAMUTUALFUNDNAV WHERE S_INFO_WINDCODE IN ({codes}) '
            f'AND PRICE_DATE<=:cutoff AND PRICE_DATE>=:start_dt AND {field}>0 '
            'GROUP BY PRICE_DATE HAVING COUNT(DISTINCT S_INFO_WINDCODE)=:n ORDER BY PRICE_DATE DESC',
            dict(binds, start_dt=(datetime.strptime(cutoff, '%Y%m%d').date()-timedelta(days=45)).strftime('%Y%m%d'), n=len(candidates)), 60)
        if not dates:
            raise ValueError('ETF全范围同日规模不完整，不以部分样本排名')
        at = str(dates[0]['PRICE_DATE'])[:8]
        assets = self.read(f'SELECT S_INFO_WINDCODE,{field} AS AUM_VALUE FROM WIND.CHINAMUTUALFUNDNAV '
                          f'WHERE S_INFO_WINDCODE IN ({codes}) AND PRICE_DATE=:at', {**{k:v for k,v in binds.items() if k != 'cutoff'}, 'at': at}, 300)
        if len(assets) != len(candidates):
            raise ValueError('ETF同日规模行不唯一或不完整')
        return dict(index_id=ROOTS[root], as_of=self.date(at), source='Wind.CHINAMUTUALFUNDNAV.'+field,
            complete=True, rows=[dict(symbol=r['S_INFO_WINDCODE'], name=candidates[r['S_INFO_WINDCODE']], index_id=ROOTS[root],
                ordinary_etf=True, aum_cny=float(r['AUM_VALUE'])*multiplier, aum_date=self.date(at)) for r in assets])


def refresh(config, local_root, old, *, now, stop=lambda: False, connector=connect, diagnostics=None):
    from dashboard.native.market_overview import previous_session
    from .overview_reference import validate
    previous = previous_session(str(now.date()))
    cutoff = previous.replace('-', '')
    result = deepcopy(old) if old else dict(schema=SCHEMA, indices={}, etfs={})
    result['fetched_at'] = now.isoformat(); errors = []; changed = 0
    db = connector(config, local_root)
    try:
        source = WindReferences(db, config, stop)
        if diagnostics is not None:
            diagnostics.update(columns={t:sorted(c) for t,c in source.columns.items()},
                aum_field_comment=source.comments.get(('CHINAMUTUALFUNDNAV',config.get('overview_wind_aum_field','F_NAV_TOTAL')),''))
        for root in ROOTS:
            for kind, fetch in (('indices', source.weights), ('etfs', source.funds)):
                try:
                    group = fetch(root, cutoff); group['reviewed_at'] = now.isoformat()
                    validate(dict(schema=SCHEMA, fetched_at=now.isoformat(), **{kind: {root: group}}))
                    result.setdefault(kind, {})[root] = group; changed += 1
                except InterruptedError:
                    raise
                except Exception as exc:
                    errors.append(root+' '+kind+'：'+(str(exc) if isinstance(exc, ValueError) else type(exc).__name__))
        members = {r['symbol'] for g in result.get('indices', {}).values() for r in g.get('rows', [])}
        mapping = deepcopy(old.get('industries', {})) if old else {}
        missing = sorted(s for s in members if not mapping.get(s, {}).get('industry'))
        if missing:
            try:
                mapping.update(source.classify(missing, cutoff))
            except InterruptedError:
                raise
            except Exception as exc:
                errors.append('行业资料待核验：'+type(exc).__name__)
        names = {}
        if changed:
            try:
                names=source.names(sorted(members))
            except InterruptedError:
                raise
            except Exception as exc:
                errors.append('成分简称待核验：'+type(exc).__name__)
        for group in result.get('indices', {}).values():
            for row in group['rows']:
                row['industry'] = mapping.get(row['symbol'], {}).get('industry')
                row['name'] = names.get(row['symbol']) or row.get('name') or row['symbol']
        result['industries'] = mapping
        result['errors'] = errors
        if diagnostics is not None:diagnostics['groups']=errors
        if not changed:
            raise ValueError('未取得可发布资料；原快照保留')
        return validate(result)
    finally:
        db.close()
