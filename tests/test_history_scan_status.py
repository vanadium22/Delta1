import json
from pathlib import Path
import unittest
from unittest.mock import Mock,patch

from dashboard.history_status import counts_ready,current_pending,progress_text
from dashboard.marketdata import history_maintenance as hm


class ScanStatusTests(unittest.TestCase):
    def fixture(self):
        from tests.test_history_maintenance import HistoryMaintenanceTests
        case=HistoryMaintenanceTests();case.setUp();self.addCleanup(case.doCleanups)
        return case

    def test_stopped_scan_cannot_reuse_earlier_zero_counts_or_pending_table(self):
        case=self.fixture();case.root.mkdir(parents=True,exist_ok=True)
        old={'state':'complete','target':'2026-10-15','scan_complete':True,'scan_id':'old',
             'pending_scan_id':'old','pending_target':'2026-10-15','pending_symbol_days':0,'missing_bars':0}
        hm._atomic_bytes(case.root/'status.json',hm._json_bytes(old))
        hm._atomic_bytes(case.root/'pending.json',hm._json_bytes({'target':'2026-10-15','scan_id':'old','jobs':[],'coverage':[{'symbol':'old'}]}))
        pending_before=(case.root/'pending.json').read_bytes()
        def interrupted(*args,**kwargs):
            state=hm.read_json(case.root/'status.json')
            self.assertFalse(state['scan_complete']);self.assertIsNone(state['missing_bars'])
            self.assertIsNone(state['pending_symbol_days']);self.assertNotEqual(state['scan_id'],'old')
            self.assertEqual(current_pending(state,hm.read_json(case.root/'pending.json'))['coverage'],[])
            kwargs['total_progress'](12560)
            raise hm.Stopped()
        with patch.object(hm,'scan',side_effect=interrupted):result=case.cycle()
        self.assertEqual(result['state'],'stopped');self.assertFalse(counts_ready(result))
        self.assertIn('缺口待核验',result['progress_message']);self.assertIn('扫描未完成',result['progress_message'])
        self.assertEqual((case.root/'pending.json').read_bytes(),pending_before)
        case.client.assert_not_called()

    def test_completed_scan_binds_counts_table_target_and_versions(self):
        case=self.fixture();result=case.cycle()
        pending=hm.read_json(case.root/'pending.json')
        self.assertTrue(counts_ready(result));self.assertEqual(result['missing_bars'],0)
        self.assertEqual(pending['scan_id'],result['scan_id']);self.assertEqual(pending['versions'],result['versions'])
        self.assertTrue(current_pending(result,pending)['coverage'])
        for modified in ({**pending,'scan_id':'other'},{**pending,'target':'2026-10-15'},{**pending,'versions':{}}):
            self.assertEqual(current_pending(result,modified),{'jobs':[],'coverage':[]})

    def test_total_progress_and_final_count_include_zero_and_short_scans(self):
        case=self.fixture();case.stores['indexes'].commit([__import__('tests.test_history_maintenance',fromlist=['bar']).bar()])
        totals=[];progress=[]
        hm.scan(case.stores,{key:s.snapshot() for key,s in case.stores.items()},{},progress=progress.append,total_progress=totals.append)
        self.assertEqual(totals,[1]);self.assertEqual(progress[-1],1)
        totals=[];progress=[]
        hm.scan({}, {}, {},progress=progress.append,total_progress=totals.append)
        self.assertEqual(totals,[0]);self.assertEqual(progress,[0])

    def test_legacy_or_incomplete_status_is_unknown_not_zero(self):
        for state in ({'state':'scanning','target':'2026-10-22','missing_bars':0,'pending_symbol_days':0},
                      {'state':'complete','missing_bars':0,'pending_symbol_days':0},
                      {'state':'stopped','scan_complete':False,'scan_groups':8500,'scan_total':12560}):
            self.assertFalse(counts_ready(state));self.assertIn('缺口待核验',progress_text(state))
            self.assertNotIn('剩余 0',progress_text(state))


if __name__=='__main__':unittest.main()
