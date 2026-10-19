"""Read-only network checks around one bounded maintenance cycle; never switches VPN."""
import json
from pathlib import Path
import sys
from datetime import datetime,timezone


def main():
    def guard(event,args):
        if event=='open' and args and str(args[0]).upper().startswith('Z:'):
            raise AssertionError('Runtime attempted Z drive I/O')
    sys.addaudithook(guard)
    from index_strategy.instant_dld.client import MarketDataClient
    from dashboard.marketdata.history_maintenance import run_cycle
    def probe():
        client=MarketDataClient(connect_timeout=4,read_timeout=8)
        try:
            result=client.fetch(['000300.SH'])
            return {k:result.get(k) for k in ('status','http_status')}
        finally:client.close()
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'realtime_before':probe()}
    result=run_cycle(Path(__file__).resolve().parent/'localsetting',force=True)
    report['history']={k:result.get(k) for k in ('state','target','pending_symbol_days','missing_bars','inserted','network_policy','error_type')}
    report['realtime_after']=probe();report['z_io']='denied_by_audit_hook'
    path=Path(__file__).resolve().parent/'runtime/history_maintenance_validation.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
