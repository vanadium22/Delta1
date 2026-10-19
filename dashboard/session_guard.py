"""Cross-process exclusion for mutually exclusive market networks."""
from contextlib import contextmanager
from dashboard.marketdata.bars import _writer_lock
from dashboard.marketdata.history_publication import maintenance_root


@contextmanager
def network_lease(config):
    roots = config.get('history_roots', [])
    if roots:
        with _writer_lock(maintenance_root(roots) / 'network_session'):
            yield
    else:
        yield


def probe_realtime(config, client_factory=None):
    """One bounded request, no persistence, no credentials or endpoint in result."""
    from dashboard.session_clock import session_policy
    policy = session_policy()
    if not policy['allowed']:
        return dict(ok=False, offline=True, message=policy['reason'])
    from index_strategy.instant_dld.client import MarketDataClient
    from dashboard.marketdata.contract_reference import active_contracts
    from dashboard.marketdata.repository import ReferenceBook
    import pandas as pd
    symbols = active_contracts(ReferenceBook(config.get('reference_file')).data,
                              str(pd.Timestamp.now(tz='Asia/Shanghai').date()))
    symbols = list(dict.fromkeys([*symbols, '000300.SH', '000016.SH', '000905.SH', '000852.SH']))
    if len(symbols) != 20:
        return dict(ok=False, message='当前合约参考不足，先在开发版更新合约；可离线进入')
    try:
        with network_lease(config):
            policy = session_policy()
            if not policy['allowed']:
                return dict(ok=False, offline=True, message=policy['reason'])
            client = (client_factory or MarketDataClient)(connect_timeout=3, read_timeout=5)
            try:
                if not session_policy()['allowed']:
                    return dict(ok=False, offline=True, message='时段结束，仅使用本地数据')
                result = client.fetch(symbols)
                ok = result.get('status') == 'success' and not result.get('missing_symbols')
                from math import isfinite
                data=(result.get('response') or {}).get('data',{})
                for symbol in symbols:
                    quote=data.get(symbol) or {};price=quote.get('latestPrice')
                    ok=ok and quote.get('securityId')==symbol and type(price) in (int,float) and isfinite(price) and 0<price<1e10
                return dict(ok=ok, message='连接验证成功；行情新鲜度仍逐行核验' if ok else
                            '连接验证失败（' + str(result.get('status', 'unknown')) + '），可重试或离线进入')
            finally:
                client.close()
    except Exception as exc:
        return dict(ok=False, message='验证未完成（' + type(exc).__name__ + '）；检查网络或其他维护任务')
