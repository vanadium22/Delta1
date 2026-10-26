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


def probe_realtime(config, client_factory=None, *, report_dir=None):
    """One bounded request, no persistence, no credentials or endpoint in result."""
    from dashboard.connection_diagnostics import error_detail,failure_message,probe_evidence,save_probe_report
    evidence=probe_evidence();stage='session_clock';outcome=None
    lock_path=None
    try:
        from dashboard.session_clock import session_policy
        policy=session_policy()
        if not policy['allowed']:
            return save_probe_report(dict(ok=False,offline=True,message=policy['reason'],diagnostics=evidence),report_dir)
        from index_strategy.instant_dld.client import MarketDataClient
        from dashboard.marketdata.contract_reference import active_contracts
        from dashboard.marketdata.repository import ReferenceBook
        import pandas as pd
        stage='reference_read';evidence['stage']=stage
        symbols=active_contracts(ReferenceBook(config.get('reference_file')).data,
                                str(pd.Timestamp.now(tz='Asia/Shanghai').date()))
        symbols=list(dict.fromkeys([*symbols,'000300.SH','000016.SH','000905.SH','000852.SH']))
        evidence['symbols']=len(symbols)
        if len(symbols)!=20:
            return save_probe_report(dict(ok=False,message='合约参考不足20个有效代码；阶段：读取合约参考；尚未请求行情。',diagnostics=evidence),report_dir)
        stage='network_lock';evidence['stage']=stage
        if config.get('history_roots'):
            lock_path=maintenance_root(config['history_roots'])/'network_session/writer.lock'
            evidence['lock_path']=str(lock_path)
        with network_lease(config):
            evidence['lock_acquired']=True
            policy = session_policy()
            if not policy['allowed']:
                outcome=dict(ok=False,offline=True,message=policy['reason'])
            else:
                stage='client_init';evidence['stage']=stage
                client=(client_factory or MarketDataClient)(connect_timeout=3,read_timeout=5)
                if isinstance(client,MarketDataClient):
                    post=client.session.post
                    def observed_post(*args,**kwargs):
                        try:return post(*args,**kwargs)
                        except Exception as exc:
                            evidence['transport_error']=error_detail(exc,'http_request')
                            raise
                    client.session.post=observed_post
                try:
                    if not session_policy()['allowed']:
                        outcome=dict(ok=False,offline=True,message='时段结束，仅使用本地数据')
                    else:
                        stage='http_request';evidence.update(stage=stage,http_attempted=True)
                        result=client.fetch(symbols)
                        evidence.update(http_status=result.get('http_status'),status=result.get('status'),
                                        elapsed_seconds=result.get('elapsed_seconds'))
                        stage='response_validation'
                        from math import isfinite
                        data=(result.get('response') or {}).get('data',{})
                        valid=isinstance(data,dict)
                        bad=[]
                        for symbol in symbols:
                            quote=data.get(symbol) if valid else None
                            price=quote.get('latestPrice') if isinstance(quote,dict) else None
                            if not (isinstance(quote,dict) and quote.get('securityId')==symbol and type(price) in (int,float) and isfinite(price) and 0<price<1e10):bad.append(symbol)
                        ok=result.get('status')=='success' and not result.get('missing_symbols') and not bad
                        evidence['invalid_or_missing_symbols']=bad
                        evidence['stage']='complete' if ok else ('http_request' if result.get('status') in ('timeout','connection_error','tls_error','proxy_error','request_error') else stage)
                        hint={'timeout':'接口等待超时；检查VPN资源和路由，未收到有效行情响应',
                              'connection_error':'接口连接失败；检查VPN资源、路由和服务端口',
                              'tls_error':'TLS证书校验失败；检查公司可信证书配置',
                              'proxy_error':'代理连接失败；核对当前请求的代理设置',
                              'http_error':'接口返回HTTP错误；请按HTTP状态码核对权限或服务',
                              'business_error':'接口返回业务失败；请按公司行情服务权限核对'}.get(result.get('status'),'接口响应不完整或代码/价格校验未通过')
                        message='当前网络可访问行情源；无需为验证另连VPN，行情新鲜度仍逐行核验' if ok else '连接验证失败：'+hint+'；阶段：'+evidence['stage']+'；状态：'+str(result.get('status','unknown'))
                        if not ok and evidence.get('http_status') is not None:message+='；HTTP '+str(evidence['http_status'])
                        outcome=dict(ok=ok,message=message)
                        if ok:evidence['network_access']='current_network_usable'
                finally:
                    import sys
                    original_error=sys.exc_info()[1]
                    try:client.close()
                    except Exception:
                        if original_error is not None:evidence['preceding_error']=error_detail(original_error,stage)
                        stage='client_close'
                        raise
            stage='network_lock_release'
    except Exception as exc:
        detail=error_detail(exc,stage,path=lock_path if stage.startswith('network_lock') else None)
        evidence.update(stage=stage,error=detail)
        outcome=dict(ok=False,message=failure_message(detail),error=detail)
    outcome['diagnostics']=evidence
    return save_probe_report(outcome,report_dir)
