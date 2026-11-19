"""Financial direction, current table evidence and within-product grouping."""
from pathlib import Path
import json
import re
import tempfile
import unittest

import numpy as np
import pandas as pd
from PIL import Image

from index_futures_basis.tests.test_recent_brief import panel
from index_futures_basis.recent_brief.data import calendar_series, session_quantiles
from index_futures_basis.recent_brief.overview import current_tables, annualized_current
from index_futures_basis.recent_brief.narrative import compose


class CurrentOverviewTests(unittest.TestCase):
    def snapshot(self, values=(-5.,-5.5,-8.,-8.5)):
        p = panel()
        for slot, value in enumerate(values, 1):
            p.loc[p.slot.eq(slot), 'annualized_basis_pct'] = value
        return p

    def test_tables_reconcile_raw_inputs_and_far_near_expiries(self):
        p = panel(); end = p.trade_date.max()
        tables = current_tables(p, calendar_series(p), end)
        self.assertEqual([t['root'] for t in tables], ['IF','IH','IC','IM'])
        rows = tables[0]['rows']
        self.assertEqual([r['label'] for r in rows], ['IF00','IF01','IF02','IF03','02−01','03−02'])
        self.assertEqual(rows[0]['contracts'], ['IF2602.CFE'])
        self.assertEqual(rows[0]['raw_price'], 990)
        self.assertEqual(rows[0]['dividend'], 1)
        for row in rows[:4]:
            self.assertAlmostEqual(row['basis_points'], row['raw_price']+row['dividend']-1000)
        for row in rows[4:]:
            self.assertAlmostEqual(row['basis_points'], row['raw_price']+row['dividend'])
            self.assertEqual(row['days'], (pd.Timestamp(row['expiries'][0])-pd.Timestamp(row['expiries'][1])).days)
            self.assertGreater(row['days'], 0)
            self.assertAlmostEqual(row['annualized_basis_pct'], row['basis_points']/1000*36500/row['days'])
        self.assertEqual(rows[4]['contracts'], ['IF2604.CFE','IF2603.CFE'])
        self.assertEqual(rows[4]['dividend'], 3)
        self.assertIsNone(tables[1]['rows'][0]['raw_price'])
        json.dumps(tables, allow_nan=False)

    def test_current_missing_dividend_is_not_displayed_as_zero(self):
        p = panel(); end = p.trade_date.max()
        p.loc[p.slot.eq(3), ['dividend_points','adjusted_futures_close','basis_points','annualized_basis_pct']] = np.nan
        table = current_tables(p, calendar_series(p), end)[0]
        self.assertIsNone(table['rows'][2]['dividend'])
        self.assertIsNone(table['rows'][4]['dividend'])
        self.assertIsNone(table['rows'][4]['basis_points'])

    def test_average_close_groups_only_within_one_product(self):
        p = self.snapshot()
        other = p.copy(); other['root'] = 'IC'; other['annualized_basis_pct'] -= 10
        text, evidence = annualized_current(pd.concat([p,other]), p.trade_date.max())
        if_row, ic_row = evidence['products'][0], evidence['products'][2]
        self.assertEqual(if_row['near']['mean_pct'], -5.25)
        self.assertEqual(if_row['far']['mean_pct'], -8.25)
        self.assertEqual(ic_row['near']['mean_pct'], -15.25)
        self.assertEqual(ic_row['far']['mean_pct'], -18.25)
        self.assertIsNone(if_row['all']['mean_pct'])
        self.assertIn('简单平均-5.25%', text)

    def test_all_four_close_uses_one_sentence_and_mean(self):
        p = self.snapshot((-5,-5.2,-5.4,-5.6))
        text, evidence = annualized_current(p, p.trade_date.max())
        row = evidence['products'][0]
        self.assertTrue(row['all']['close'])
        self.assertAlmostEqual(row['all']['mean_pct'], -5.3)
        self.assertEqual(row['text'], 'IF四档年化接近，00—03简单平均-5.30%。')

    def test_divergent_near_expiry_and_far_values_are_individual(self):
        p = self.snapshot((-125.5,-16.32,-9.62,-7.28))
        p.loc[p.slot.eq(1), 'days_to_expiry'] = 1
        _, evidence = annualized_current(p, p.trade_date.max())
        row = evidence['products'][0]
        self.assertTrue(all(row[g]['mean_pct'] is None for g in ('all','near','far')))
        for text in ('00为-125.50%', '01为-16.32%', '02为-9.62%', '03为-7.28%', '距到期1天'):
            self.assertIn(text, row['text'])

    def test_missing_expired_and_opposite_sign_values_do_not_average(self):
        for column, value in [('days_to_expiry',0), ('annualized_basis_pct',np.nan), ('calendar_known',False)]:
            p = self.snapshot((-5,-5,-5,-5))
            p.loc[p.slot.eq(1), column] = value
            _, evidence = annualized_current(p, p.trade_date.max())
            self.assertIsNone(evidence['products'][0]['all']['mean_pct'])
            self.assertIsNone(evidence['products'][0]['near']['mean_pct'])
        p = self.snapshot((-.1,.1,-5,-5))
        _, evidence = annualized_current(p, p.trade_date.max())
        self.assertFalse(evidence['products'][0]['near']['close'])

    def test_cross_rank_is_reversed_with_direction_not_only_renamed(self):
        p = pd.concat([panel().tail(4).assign(trade_date=day) for day in pd.bdate_range('2025-01-01',periods=65)], ignore_index=True)
        p['futures_close'] = p.futures_close.astype(float)
        p['adjusted_futures_close'] = p.adjusted_futures_close.astype(float)
        end = p.trade_date.max()
        p.loc[p.trade_date.eq(end) & p.slot.eq(3), 'adjusted_futures_close'] -= 10
        cross = calendar_series(p)
        q = session_quantiles(cross,end,'pair')
        self.assertEqual(q[q.pair.eq('02−01')].iloc[0].percentile, 0)
        self.assertTrue(cross.expiry_gap_days.gt(0).all())

    def test_roll_jump_does_not_produce_absolute_trend_or_anomaly(self):
        frames = []
        for i,day in enumerate(pd.bdate_range('2025-01-01',periods=65)):
            p = panel().tail(4).assign(trade_date=day)
            p['roll_day'] = i == 45
            if i >= 45:
                p['instrument_id'] = p.instrument_id.str.replace('26','27')
                p['basis_points'] -= 100
            frames.append(p)
        p = pd.concat(frames,ignore_index=True)
        result = compose(p,calendar_series(p),None,None,None,p.trade_date.max())
        self.assertFalse(result['absolute']['overview']['IF']['complete'])
        self.assertEqual(result['absolute']['selected'], [])
        self.assertIn('未据换档跳变判断走势', result['sections'][0]['text'])

    def test_current_tables_are_native_and_before_chart_pages(self):
        from docx import Document
        from index_futures_basis.recent_brief.charts import setup
        from index_futures_basis.recent_brief.documents import export_documents, WORD_NAME, PDF_NAME
        from index_futures_basis.recent_brief.workflow import FIGURES
        setup()
        p = panel(); end = p.trade_date.max()
        info = {'as_of':str(end.date()), 'dividend_date':'2026-01-01',
                'narrative':'综合观察正文', 'current_tables':current_tables(p,calendar_series(p),end)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in FIGURES:
                Image.new('RGB',(380,560),'white').save(root/name)
            result = export_documents(root,FIGURES,info)
            document = Document(root/WORD_NAME)
            self.assertEqual(len(document.tables), 4)
            for table in document.tables:
                self.assertEqual(len(table.rows), 7)
                self.assertEqual(table.cell(5,0).text, '02−01')
                self.assertEqual(table.cell(6,0).text, '03−02')
            self.assertIn('IF2604.CFE\n− IF2603.CFE',document.tables[0].cell(5,1).text)
            pdf = (root/PDF_NAME).read_bytes()
            self.assertEqual(len(re.findall(rb'/Type\s*/Page\b',pdf)),11)
            self.assertEqual(result['pages'],11)
