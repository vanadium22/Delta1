"""Public, market-data-free boundary fixtures; runs on company checkout too."""
import unittest,math,json
from pathlib import Path
from .core import *
from .minute import compute
from .service import CARDS,variants,field_specs


class CoreContract(unittest.TestCase):
    def test_public_acceptance_contract(self):
        cases=json.loads((Path(__file__).parent/'acceptance_cases.json').read_text(encoding='utf8'));tested=[]
        sessions=[dict(id='AM',first_end='09:31:00',last_end='11:30:00'),dict(id='PM',first_end='13:01:00',last_end='15:00:00')]
        grid=minute_grid('2026-10-09',sessions)
        # Deterministic operator fixture, never offered to the application as market data.
        rows={g['timestamp']:dict(F=100+math.sin(i*.4)+i*.02,N=102+math.cos(i*.3),S=101+math.sin(i*.25),V=10,VN=20) for i,g in enumerate(grid)}
        for c in cases:
            k=c['id'];e=c['expected'];v=c['input'];tested.append(k)
            if k in ('T4','T5'):
                actual=basis(Value(v['F']),Value(v['S']),v['T'])
                for key,want in e.items():self.assertIsNone(actual[key].value) if want is None else self.assertAlmostEqual(actual[key].value,want)
            elif k=='calendar_near4':self.assertAlmostEqual(calendar(Value(101),Value(100),Value(100),63)['ac'].value,e['ac'])
            elif k=='constant_rank':
                pct,z=statistic([Value(2)]*21,20);self.assertEqual(pct.value,50);self.assertIsNone(z.value)
            elif k=='constant_path':self.assertIsNone(efficiency([Value(2)]*6,5).value);self.assertEqual(volatility([Value(0)]*30,29).value,0)
            elif k=='zero_weights':self.assertEqual(total([Value(0)]*5).value,0);self.assertIsNone(weighted([Value(1)]*5,[Value(0)]*5).value)
            elif k=='candidate_missing':self.assertIsNone(candidate(Value(0),[Value(1)],[invalid('INPUT_MISSING')],Value(.1),[Value(1)]).value)
            elif k=='candidate_valid_zero':self.assertEqual(candidate(Value(0),[Value(1)],[Value(.01)],Value(.1),[Value(1)]).value,0)
            elif k=='minute_session_start':
                out=compute(rows,grid,70,63)
                for field,want in [('z_b',e['first_z']),('A_rv30',e['first_rv']),('A_resid',e['first_residual']),('event_b',e['first_event'])]:self.assertEqual(next(g['timestamp'][11:16] for g,d in zip(grid,out) if d[field].value is not None),want)
            elif k=='noon_axis':self.assertEqual(grid[119]['timestamp'][11:16],'11:30');self.assertEqual(grid[120]['timestamp'][11:16],'13:01')
            elif k=='missing_minute':
                missing=dict(rows);del missing[grid[29]['timestamp']];out=compute(missing,grid,70,63);self.assertIsNone(out[29]['b'].value);self.assertEqual(len(out),240);self.assertEqual(grid[30]['timestamp'][11:16],'10:01')
            elif k=='zero_capacity':self.assertEqual(capacity(Value(0),Value(100),Value(100),Value(100),Value(1))[2].value,0)
            else:self.fail('Unexecuted acceptance case: '+k)
        self.assertEqual(len(tested),12)
    def test_catalog_and_formula_assets(self):
        self.assertEqual([sum(k.startswith(g) for k in CARDS) for g in 'ABC'],[12,10,10])
        for code in CARDS:
            for v in variants(code):self.assertTrue(field_specs(code,v))
            for theme in ('public','private'):self.assertTrue((Path(__file__).parent/'formula_assets'/f'{code}_{theme}.png').is_file())
    def test_price_pair_and_dependency_validation(self):
        self.assertIsNone(basis(raw(0,'price'),Value(100),5)['b'].value)
        a=basis(Value(99),Value(100),4);b=basis(Value(99),Value(100),5)
        self.assertEqual(cross(a,b)['G'].value,0);self.assertIn('DTE_LT5',cross(a,b)['Ga'].reasons)
        self.assertEqual(cross(a,b,False)['G'].reasons,('PAIR_MISMATCH',))
        self.assertIsNone(weighted([invalid('WINDOW_GAP')],[Value(0)]).value)
        self.assertIsNone(capacity(Value(0),invalid('INPUT_MISSING'),Value(1),Value(1),Value(1))[2].value)
    def test_zero_residual_variance_keeps_beta(self):
        x=[Value(i*.001) for i in range(32)];y=[2*a+1 for a in x];r=regression(y,x,31)
        self.assertAlmostEqual(r['beta'].value,2);self.assertAlmostEqual(r['resid'].value,0);self.assertIsNone(r['z'].value)
        y[-1]=invalid('INPUT_MISSING');self.assertAlmostEqual(regression(y,x,31)['beta'].value,2)
if __name__=='__main__':unittest.main(verbosity=2)
