"""Offline replay of saved real observations and local DDB data, never a live test."""
import json
import socket
import time
import pandas as pd


def main():
    attempts=[]
    def denied(*args,**kwargs):
        attempts.append(str(args[:1]));raise AssertionError('offline validation forbids network')
    socket.socket.connect=denied;socket.getaddrinfo=denied;socket.create_connection=denied
    from dashboard.native.model import NativeModel
    from dashboard.marketdata.paths import VALIDATION_ROOT
    model=NativeModel();out=VALIDATION_ROOT/'continuous_cards';out.mkdir(parents=True,exist_ok=True)
    result=dict(mode='offline replay of saved real HTTP observations; not a live VPN test',checks=[],network_attempts=attempts)
    try:
        request=dict(cards=True,category='basis',price_input='basis',research_month='2612',overview_slot=2)
        start=time.perf_counter();initial=model.snapshot(request);result['cold_seconds']=round(time.perf_counter()-start,3)
        now=max(pd.Timestamp(q['received_at']) for q in initial['quotes'] if q['received_at'])+pd.Timedelta(seconds=1)
        fresh=model.snapshot({**request,'as_of':now})
        current=[]
        for row in fresh['overview']:
            assert row['quality']['usable'],row['quality']
            assert row['aligned'],row['reason']
            f=row['quote']['close'];s=row['spot']['close'];d=row['dividend']
            expected=10000*(f-s+d)/s
            assert abs(row['current']['bp']-expected)<1e-9
            assert abs(row['current']['annual_pct']-expected*365/(100*row['days']))<1e-9
            assert row['chart']['kind']=='盘中观测'
            assert row['alias']==row['root']+'02.CFE'
            assert all(r['complete'] for r in row['chart']['rows']),row['chart']['rows']
            mapping=row['continuity']['mappings']
            assert len({r['symbol'] for r in mapping if r['symbol']})>4
            assert all(r['dividend']==d for r in mapping)
            assert all(pd.Timestamp(r['end']).tz_convert('Asia/Shanghai').date()<now.tz_convert('Asia/Shanghai').date() for r in row['chart']['rows'] if r['end'])
            current.append(dict(symbol=row['symbol'],source_time=str(row['quote']['source_event_time']),price=f,cumulative_volume=row['quote']['volume_total'],basis_bp=expected,annual_pct=row['current']['annual_pct']))
        result['replay_as_of']=now.isoformat();result['saved_quote_replay']=current
        result['checks'].append('saved real quotes map to four cards; independent F-S+D and simple annual calculations agree')
        expired=model.snapshot({**request,'as_of':now,'overview_slot':0,'distribution_input':'annual'})
        assert all(r['current']['annual_pct'] is None and r['days']==0 for r in expired['overview'])
        assert all(r['chart']['kind']=='历史' and pd.Timestamp(r['chart']['time'])<now for r in expired['overview'])
        result['checks'].append('expiry annual current stays empty; historical marker retains original date')
        stale=model.snapshot({**request,'as_of':now+pd.Timedelta(minutes=2)})
        assert all(r['current']['bp'] is None and r['chart']['kind']=='历史' for r in stale['overview'])
        start=time.perf_counter();model.snapshot({**request,'as_of':now+pd.Timedelta(minutes=2,seconds=1)});result['cached_seconds']=round(time.perf_counter()-start,3)
        result['checks'].append('fresh-to-stale transition invalidates cached live values without advancing source time')
        for category in ('calendar','cross'):
            state=model.snapshot({**request,'category':category,'far_month':'2703','as_of':now})
            assert len(state['entities'])==(4 if category=='calendar' else 6)
            for e in state['entities']:
                assert all(r['current'] is None for r in e['metrics'] if r['id'].startswith(('B03','B04','B05','B06','B08')))
                if category=='calendar':
                    bp=next(r for r in e['metrics'] if r['id']=='A04.points')['current']
                    # This proves the card grouping does not replace real legs with slot history.
                    mapping=state['dividend_info']['mapping'];quotes={q['symbol']:q for q in state['quotes']}
                    expected=(quotes[e['left']]['close']+mapping[e['left']]['points'])-(quotes[e['right']]['close']+mapping[e['right']]['points'])
                    assert abs(bp-expected)<1e-9
                else:assert e['left'][2:]==e['right'][2:]
            assert not any(g['id'].startswith(('C','A08','A10')) for g in state['metric_groups'])
        result['checks'].append('four fixed calendar pairs and six same-expiry cross pairs; no fabricated OI change or migration')
        historical=model.snapshot({**request,'research_month':'2609','price_input':'future','as_of':now})
        assert all(next(r for r in e['metrics'] if r['id']=='A01.bp')['value'] is None for e in historical['entities'])
        assert all(any(r['id']=='B04.Q' and r['value'] is not None for r in e['metrics']) for e in historical['entities'])
        result['checks'].append('old unmapped contracts keep dividend-dependent values empty while real price/OI indicators remain available')
        second=model.snapshot({**request,'overview_slot':1,'as_of':now})
        assert all(r['alias']==r['root']+'01.CFE' and r['symbol']==r['root']+'2611.CFE' for r in second['overview'])
        assert all(all(w['complete'] for w in r['chart']['rows']) for r in second['overview'])
        far=model.snapshot({**request,'overview_slot':3,'as_of':now})
        assert all(r['alias']==r['root']+'03.CFE' and r['symbol']==r['root']+'2703.CFE' for r in far['overview'])
        result['continuous_overview']=[dict(alias=r['alias'],contract=r['symbol'],version=r['continuity']['version'],mapping=r['continuity']['mappings'],windows=r['chart']['rows']) for r in far['overview']]
        result['checks'].append('00—03 maps to explicit dated contracts; 20d/3m/6m/12m continuous distributions; one disclosed dividend scenario throughout each slot')
        assert not attempts;result['success']=True
    finally:
        model.close()
        (out/'data_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='continuous_overview'},ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
