from pathlib import Path
import tempfile
import unittest
import pandas as pd
import pyarrow.parquet as pq
from dashboard.native.nonregression import frame_index
from tests.test_numeric_model import fixture


class StartupDataTests(unittest.TestCase):
    def test_utc_nanoseconds_null_and_projected_reads_match_arrow_scalars(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=fixture(Path(tmp)/'history')
            snap=store.snapshot();row=store._rows(snap)[0]
            row.update(revision=row['revision']+1,
                recorded_at=pd.Timestamp('2026-10-19T01:00:00.123456789Z'),available_at=None)
            store.commit([row]);part=store.snapshot()['parts'][-1]
            manifest={'parts':[part]}
            expected=pq.read_table(store._path(part['path'])).to_pylist()
            actual=store._rows(manifest)
            self.assertEqual(actual,expected)
            self.assertEqual(actual[0]['recorded_at'].nanosecond,789)
            columns=['event_time','recorded_at','available_at','close']
            self.assertEqual(store._rows(manifest,columns=columns),[{k:r[k] for k in columns} for r in expected])

    def test_research_drops_heavy_attrs_without_mutating_source_provenance(self):
        frame=pd.DataFrame(dict(event_time=pd.to_datetime(['2026-10-16T07:00:00Z']),close=[0.]))
        frame.attrs={'dataset':{'instruments':{'IF2611.CFE':{'asset_type':'cn_index_future'}}},'version':'frozen'}
        result=frame_index(frame)
        self.assertEqual(result.attrs,{})
        self.assertEqual(result.iloc[0]['close'],0)
        self.assertEqual(frame.attrs['version'],'frozen')
        self.assertIn('IF2611.CFE',frame.attrs['dataset']['instruments'])
