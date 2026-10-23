"""Deterministic acceptance, source replay and desktop contract checks. No live interfaces."""
import json,math,unittest
from pathlib import Path
from .core import *
from .minute import compute
from .service import Service,CARDS,variants,field_specs,display
from .sources import SPEC


@unittest.skipUnless(SPEC.exists(),'真实研究归档未安装；独立边界验收见 test_core')
class Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=json.loads(SPEC.read_text(encoding='utf8'));cls.service=Service();cls.archive=cls.service.source('replay')
    def test_json_acceptance_cases(self):
        cases={c['id']:c for c in self.spec['acceptance_cases']};seen=[]
        for cid in ('T4','T5'):
            c=cases[cid];d=basis(raw(c['input']['F'],'price'),raw(c['input']['S'],'price'),c['input']['T'])
            for k,v in c['expected'].items():self.assertAlmostEqual(d[k].value,v) if v is not None else self.assertIsNone(d[k].value)
            seen.append(cid)
        c=cases['calendar_near4'];d=calendar(Value(101),Value(100),invalid('INPUT_MISSING'),63)
        self.assertAlmostEqual(d['ac'].value,c['expected']['ac']);self.assertIsNone(d['cal'].value);seen.append(c['id'])
        p,z=statistic([Value(2)]*21,20);self.assertEqual(p.value,50);self.assertEqual(z.reasons,('STD_ZERO',));seen.append('constant_rank')
        self.assertEqual(efficiency([Value(2)]*6,5).reasons,('FLAT_PATH',));self.assertEqual(volatility([Value(0)]*30,29).value,0);seen.append('constant_path')
        w=[Value(0)]*5;self.assertEqual(total(w).value,0);self.assertEqual(weighted([Value(1)]*5,w).reasons,('NO_WEIGHT',));seen.append('zero_weights')
        self.assertIsNone(candidate(Value(0),[Value(1)],[invalid('INPUT_MISSING')],Value(.1),[Value(1)]).value);seen.append('candidate_missing')
        self.assertEqual(candidate(Value(0),[Value(1)],[Value(.01)],Value(.1),[Value(1)]).value,0);seen.append('candidate_valid_zero')
        sessions=self.spec['coordinates']['minute']['sessions'];grid=minute_grid('2026-10-09',sessions);rows={r['timestamp']:r['raw'] for r in self.spec['datasets']['minute']};values=compute(rows,grid,70,63)
        for field,stamp in [('z_b','10:01'),('A_rv30','10:01'),('A_resid','10:02'),('event_b','10:03')]:
            first=next(m['timestamp'][11:16] for m,v in zip(grid,values) if v[field].value is not None);self.assertEqual(first,stamp)
        seen.append('minute_session_start');self.assertEqual((grid[119]['timestamp'][11:16],grid[120]['timestamp'][11:16]),('11:30','13:01'));seen.append('noon_axis')
        del rows[grid[29]['timestamp']];missing=compute(rows,grid,70,63)
        self.assertIsNone(missing[29]['b'].value);self.assertEqual(grid[30]['timestamp'][11:16],'10:01');self.assertEqual(len(missing),240);seen.append('missing_minute')
        self.assertEqual(capacity(Value(0),Value(100),Value(100),Value(100),Value(1))[2].value,0);seen.append('zero_capacity')
        self.assertEqual(set(seen),set(cases))
    def test_all_real_sample_fields(self):
        count=0
        for c in self.spec['indicators']:
            for x in variants(c['id']):
                r=self.service.query(c['id'],x,day='2026-10-09')
                for k,ps in r['series'].items():
                    if k not in c['sample_values']:continue
                    count+=1;a=ps[-1]['value'];b=c['sample_values'][k]['value']
                    if b is None:self.assertIsNone(a,(c['id'],x,k))
                    else:self.assertTrue(a is not None and math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-7),(c['id'],x,k,a,b))
        self.assertGreaterEqual(count,150)
    def test_cross_guard_and_zero_dependencies(self):
        u=basis(Value(99),Value(100),4);v=basis(Value(99),Value(100),5)
        d=cross(u,v);self.assertEqual(d['G'].value,0);self.assertIsNone(d['Ga'].value);self.assertIn('DTE_LT5',d['Ga'].reasons)
        self.assertEqual(cross(u,v,False)['G'].reasons,('PAIR_MISMATCH',))
        self.assertIsNone(weighted([invalid('INPUT_MISSING')],[Value(0)]).value)
        self.assertIsNone(capacity(Value(0),invalid('INPUT_MISSING'),Value(1),Value(1),Value(1))[2].value)
        self.assertEqual(capacity(Value(0),Value(1),Value(1),Value(1),Value(0))[2].value,None)
    def test_partial_outputs_and_regression(self):
        from .daily import single
        rows=[dict(close=100,spot=None,volume=0,oi=5,open=100,high=100,low=100)]*65
        ds=single(rows,[f'2026-01-{1+i%28:02d}' for i in range(65)],'2026-12-18',300)
        self.assertEqual(ds[-1]['nominal'].value,3);self.assertIsNone(ds[-1]['basis_cash'].value)
        self.assertIsNone(ds[-1]['K'].value);self.assertEqual(ds[-1]['Q'].value,0);self.assertIsNone(ds[-1]['clv'].value)
        x=[Value(i*.0001) for i in range(32)];y=[Value(2*v.value+.001) for v in x]
        r=regression(y,x,31);self.assertAlmostEqual(r['beta'].value,2);self.assertAlmostEqual(r['resid'].value,0);self.assertIsNone(r['z'].value)
        y[-1]=invalid('INPUT_MISSING');r=regression(y,x,31);self.assertAlmostEqual(r['beta'].value,2);self.assertIsNone(r['resid'].value)
        self.assertEqual(regression([Value(0)]*32,[Value(0)]*32,31)['beta'].reasons,('REG_DEGENERATE',))
    def test_noon_and_missing_are_different(self):
        m=self.spec['datasets']['minute'];grid=minute_grid('2026-10-09',self.spec['coordinates']['minute']['sessions']);rows={r['timestamp']:r['raw'] for r in m};v=compute(rows,grid,70,63)
        self.assertIsNotNone(v[120]['center_b'].value);self.assertIsNone(v[120]['A_resid'].value);self.assertIsNotNone(v[151]['A_resid'].value)
        self.assertIsNone(v[120]['event_b'].value);self.assertEqual(v[-1]['count_b'].value,3)
        del rows[grid[29]['timestamp']];v=compute(rows,grid,70,63)
        self.assertIsNone(v[-1]['center_b'].value);self.assertIsNone(v[-1]['events_b'].value);self.assertIsNotNone(v[-1]['A_resid'].value)
        self.assertIn('WINDOW_GAP',v[-1]['center_b'].reasons)
        custom=minute_grid('2026-10-09',[dict(id='AM',first_end='09:31:00',last_end='10:10:00')]);short=compute(rows,custom,70,63)
        self.assertEqual(len(short),40)
    def test_switch_full_history_and_cache(self):
        b=self.service.query('A02','b',day='2026-04-10');a=self.service.query('A02','a',day='2026-04-10')
        self.assertEqual(b['series']['b_pct'][-1]['value'],90);self.assertEqual(a['series']['a_pct'][-1]['value'],15)
        self.assertNotEqual(b['cache_key'],a['cache_key']);self.assertEqual(a['fields'][2]['unit'],'pp')
        l=self.service.query('B02','l',day='2026-10-09');ac=self.service.query('B02','ac',day='2026-10-09')
        self.assertAlmostEqual(l['series']['l_z'][-1]['value'],ac['series']['ac_z'][-1]['value'])
        identity=['IF2612.CFE'];fixed=self.service.query('A02','a',identity=identity,day='2026-10-09');self.assertNotEqual(fixed['cache_key'],a['cache_key'])
        returned=self.service.query('A02','b',day='2026-04-10');self.assertEqual(returned['cache_key'],b['cache_key'])
    def test_all_entries_and_finite_contract(self):
        self.assertEqual([sum(k.startswith(g) for k in CARDS) for g in 'ABC'],[12,10,10])
        for code in CARDS:
            r=self.service.query(code,day='2026-10-09');json.dumps(r,allow_nan=False)
            for field,series in r['series'].items():
                for p in series:
                    self.assertEqual(p['status']=='VALID',p['value'] is not None)
                    self.assertEqual(bool(p['reason_codes']),p['value'] is None)
                    if p['value'] is not None:self.assertTrue(math.isfinite(p['value']))
        zero={'value':0,'field':'K','unit':'ratio'};self.assertEqual(display(zero),('0.00','%'))
    def test_roll_line_break_and_own_history(self):
        r=self.service.query('A02','b');ps=r['series']['b_pct'];rolls=[i for i,p in enumerate(ps) if p['break_before']]
        self.assertTrue(rolls)
        self.assertTrue(any(ps[i]['value'] is not None for i in rolls))
        for i in rolls:self.assertNotEqual(ps[i-1]['contract_ids'],ps[i]['contract_ids'])
        self.assertEqual(len(ps),242)
    def test_archive_unknown_is_not_invented(self):
        service=Service();source=service.source('replay');source.raw={}
        r=service.query('A11','b');empty=[p for p in r['series']['C2'] if p['value'] is None]
        self.assertTrue(empty);self.assertTrue(all(p['reason_codes']==['ARCHIVE_REASON_UNKNOWN'] for p in empty))
        with self.assertRaises(ValueError):service.query('B02','l')


if __name__=='__main__':unittest.main(verbosity=2)
