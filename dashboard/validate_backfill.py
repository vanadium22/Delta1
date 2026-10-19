"""One-shot validation of local history and all continuous annual distributions."""
import json
from pathlib import Path

import pandas as pd

from dashboard.marketdata.bars import BarDataset, _atomic_bytes, _json_bytes
from dashboard.marketdata.history_backfill import DEST, fingerprint
from dashboard.native.collection import CollectionJob
from dashboard.native.instruments import UNDERLYINGS
from dashboard.native.model import NativeModel


def main():
    model=NativeModel();job=CollectionJob(model.local_root)
    report={'datasets':{},'slots':{},'source_files_unchanged':True}
    try:
        for root in model.config['history_roots']:
            store=BarDataset(root);desc=store.descriptor;snapshot=store.snapshot()
            base=BarDataset(desc['base_dataset']);before=base.snapshot()
            assert before['version']==desc['base_version'],'original history was changed'
            totals=lambda snap:{f:sum(p['rows'] for p in snap['parts'] if p['frequency']==f) for f in ('1d','1m')}
            old,new=totals(before),totals(snapshot)
            report['datasets'][desc['dataset_id']]=dict(root=root,original_unchanged=True,before=old,after=new,
                                                      added={k:new[k]-old[k] for k in old})
        paths={}
        for audit in (DEST/'audits').glob('*.json'):
            data=json.loads(audit.read_text(encoding='utf8'))
            for item in data.get('evidence',[]):
                if item.get('fingerprint'):paths[item['path']]=item['fingerprint']
        report['source_files_checked']=len(paths)
        for path,expected in paths.items():
            assert fingerprint(Path(path))==expected,('source changed after read',path)
        request=dict(cards=True,category='basis',price_input='annual',distribution_input='annual',research_month='2706')
        model.snapshot({**request,'overview_slot':3})
        indices={v[0] for v in UNDERLYINGS.values()}
        job.start(model.config['realtime_root'],list(indices),indices,model.config['reference_file'],once=True,auto_roll=True)
        job.worker.join(timeout=45)
        assert not job.running()
        report['collection']=job.state()
        assert report['collection']['last_result']=='success',report['collection']
        as_of=pd.Timestamp.now(tz='UTC').isoformat()
        for slot in range(4):
            state=model.snapshot({**request,'overview_slot':slot,'as_of':as_of})
            report['slots'][slot]=[]
            for row in state['overview']:
                assert row['continuity']['alias']==row['alias']
                assert row['chart']['unit']=='%'
                assert all(r['available'] and r['percentile'] is not None for r in row['chart']['rows']),row['chart']
                report['slots'][slot].append(dict(alias=row['alias'],symbol=row['symbol'],kind=row['chart']['kind'],
                                                  rows=row['chart']['rows'],dividend=row['dividend']))
        mapping=state['dividend_info']['mapping']
        report['dividends']={}
        for root in UNDERLYINGS:
            new,old=root+'2706.CFE',root+'2703.CFE'
            assert mapping[new]['points']==mapping[old]['points']
            assert mapping[new]['inherited_from']==old
            report['dividends'][new]=dict(points=mapping[new]['points'],from_contract=old)
        report.update(success=True,as_of=as_of,distribution_windows=64)
    finally:
        job.stop()
        if job.worker:job.worker.join(timeout=15)
        model.close()
        out=Path(__file__).resolve().parent/'runtime/history_backfill_validation.json'
        _atomic_bytes(out,_json_bytes(report))
    print(json.dumps({k:v for k,v in report.items() if k not in ('slots','collection')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
