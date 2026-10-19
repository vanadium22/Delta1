"""Bounded real rollover integration test; explicit network action, no VPN changes."""
import json
from pathlib import Path

from dashboard.native.collection import CollectionJob
from dashboard.native.model import NativeModel
from dashboard.native.instruments import UNDERLYINGS
from index_strategy.instant_dld.service import write_json


def main():
    model=NativeModel()
    report={}
    job=CollectionJob(model.local_root)
    try:
        report['reference']=model.sync_contract_reference()
        request=dict(cards=True,category='basis',price_input='basis',research_month='2706',overview_slot=3)
        model.snapshot(request)  # Warm local history before testing freshness.
        indices={v[0] for v in UNDERLYINGS.values()}
        job.start(model.config['realtime_root'],list(indices),indices,model.config['reference_file'],once=True,auto_roll=True)
        job.worker.join(timeout=45)
        assert not job.running(),'bounded collection did not finish'
        report['collection']=job.state()
        assert report['collection']['last_result']=='success',report['collection']
        assert not report['collection']['missing_symbols'],report['collection']
        report['slots']={}
        for slot in range(4):
            state=model.snapshot({**request,'overview_slot':slot})
            report['slots'][slot]=[{k:r.get(k) for k in ('alias','symbol','quality','dividend','dividend_inherited_from','current')} for r in state['overview']]
            assert all(r['quality']['usable'] for r in state['overview']),report['slots'][slot]
            assert all(r['current']['bp'] is not None for r in state['overview']),report['slots'][slot]
        report['new_contract_dividends']={}
        mapping=state['dividend_info']['mapping']
        for root in UNDERLYINGS:
            new,previous=root+'2706.CFE',root+'2703.CFE'
            assert mapping[new]['points']==mapping[previous]['points']
            assert mapping[new]['inherited_from']==previous
            report['new_contract_dividends'][new]=mapping[new]
        assert len(state['quotes'])==20
        assert all(q['quality']['usable'] for q in state['quotes'])
        report['quotes']=[{k:q.get(k) for k in ('symbol','close','source_event_time','quality')} for q in state['quotes']]
        report['new_contract_metrics']={e['title']:{r['id']:r['current'] for r in e['metrics'] if r['current'] is not None} for e in state['entities']}
        report['success']=True
    finally:
        job.stop()
        if job.worker:job.worker.join(timeout=15)
        model.close()
        out=Path(__file__).resolve().parent/'runtime'/'rollover_validation.json'
        write_json(out,json.loads(json.dumps(report,ensure_ascii=False,default=str,allow_nan=False)))
    print(json.dumps(dict(success=True,collection=report['collection'],dividends=report['new_contract_dividends'],report=str(out)),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
