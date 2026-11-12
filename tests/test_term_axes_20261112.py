"""Daily stable term-curve axes and retained points for all four products."""
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import pandas as pd

from dashboard.native.bootstrap import configure_qt
configure_qt()
from dashboard.marketdata.overview_display_cache import preserve
from dashboard.native.market_overview_view import MarketOverviewPanel
from dashboard.native.term_curve import DailyRanges,axis_day
from tests.test_market_overview import NOW
from tests.test_market_overview_ui import APP,state


def item(slot,value):return dict(slot=slot,annual_pct=value)


class DailyRangeTests(unittest.TestCase):
    def test_initial_margin_then_only_extend_outside_and_reset_next_day(self):
        ranges=DailyRanges();day='2026-11-12'
        original=[item(0,-7),item(1,-6.5),item(2,-6),item(3,-5)]
        self.assertEqual(ranges.update('IH',day,original),(-9,-3))
        for value in (-7.1,-8.99,-9):
            changed=deepcopy(original);changed[0]['annual_pct']=value
            self.assertEqual(ranges.update('IH',day,changed),(-9,-3))
        changed=deepcopy(original);changed[0]['annual_pct']=-9.5
        self.assertEqual(ranges.update('IH',day,changed),(-11.5,-3))
        self.assertEqual(ranges.update('IH',day,original),(-11.5,-3))
        changed[3]['annual_pct']=-2.5
        self.assertEqual(ranges.update('IH',day,changed),(-11.5,-.5))
        self.assertEqual(ranges.update('IH','2026-11-13',original),(-9,-3))

    def test_newly_available_slot_gets_margin_without_shrinking_other_bounds(self):
        ranges=DailyRanges();day='2026-11-12'
        self.assertEqual(ranges.update('IF',day,[item(0,-5)]),(-7,-3))
        self.assertEqual(ranges.update('IF',day,[item(0,-5),item(1,-7)]),(-9,-3))
        self.assertEqual(ranges.update('IF',day,[item(1,-7)]),(-9,-3))
        self.assertEqual(ranges.update('IF',day,[]),(-9,-3))
        self.assertEqual(ranges.update('IM',day,[item(0,2),item(1,3)]),(0,5))
        self.assertIsNone(ranges.update('IF','2026-11-13',[]))

    def test_day_comes_from_shanghai_snapshot_not_quote_date(self):
        self.assertEqual(axis_day('2026-11-12T15:59:59+00:00'),'2026-11-12')
        self.assertEqual(axis_day('2026-11-12T16:00:00+00:00'),'2026-11-13')
        self.assertEqual(axis_day('2026-11-12'),'2026-11-12')

    def test_horizontal_range_uses_all_known_maturities_and_stays_stable(self):
        ranges=DailyRanges();day='2026-11-12'
        rows=[dict(days=value) for value in (10,40,130,220)]
        self.assertEqual(ranges.x_range('IH',day,rows,[]),(-11,241))
        self.assertEqual(ranges.x_range('IH',day,rows[1:3],[]),(-11,241))
        self.assertEqual(ranges.x_range('IF',day,[dict(days=100),dict(days=110)],[]),(97,113))
        shifted=[dict(days=value) for value in (9,39,129,219)]
        self.assertEqual(ranges.x_range('IH',day,shifted,[]),(-11,241))
        self.assertEqual(ranges.x_range('IH','2026-11-13',shifted,[]),(-12,240))


class FourProductChartTests(unittest.TestCase):
    def test_all_four_retain_missing_points_and_share_stable_daily_axes(self):
        original=state();market=original['market_overview']
        for r in market['futures']:r['annual_pct']=(-7.,-6.5,-5.5,-5.)[r['slot']]
        with tempfile.TemporaryDirectory() as tmp:
            model=SimpleNamespace(local_root=Path(tmp),config={},overview_write_cache=True)
            before=deepcopy(market);preserve(model,before,NOW)
            missing=deepcopy(market)
            for row in missing['futures']:
                if row['slot'] in (1,2):row.update(annual_pct=None,basis_points=None)
            preserve(model,missing,NOW+pd.Timedelta(seconds=1))
            panel=MarketOverviewPanel()
            try:
                panel.render(dict(as_of=NOW.isoformat(),market_overview=missing))
                APP.processEvents()
                detail=panel.views['futures']
                for root in ('IF','IH','IC','IM'):
                    chart=panel.charts[root]
                    self.assertEqual([p['slot'] for p in chart.curve_points],[0,1,2,3])
                    self.assertEqual([p['slot'] for p in chart.curve_points if p['saved']],[1,2])
                    self.assertEqual(tuple(chart.curve.viewRange()[1]),(-9.,-3.))
                    detail.select(root)
                    APP.processEvents()
                    self.assertEqual([p['slot'] for p in detail.curve_points],[0,1,2,3])
                    self.assertEqual(tuple(detail.curve.viewRange()[1]),(-9.,-3.))
                    self.assertIs(chart.axis_ranges,detail.axis_ranges)
                initial_x=tuple(panel.charts['IH'].curve.viewRange()[0])
                absent=next(r for r in missing['futures'] if r['root']=='IH' and r['slot']==3)
                absent.update(annual_pct=None,basis_points=None);absent.pop('basis_display',None)
                panel.render(dict(as_of=NOW.isoformat(),market_overview=missing))
                APP.processEvents()
                self.assertEqual(tuple(panel.charts['IH'].curve.viewRange()[0]),initial_x)
                self.assertEqual([p['slot'] for p in panel.charts['IH'].curve_points],[0,1,2])
                absent['annual_pct']=-5.
                # A small move stays inside the previous range for every root.
                for row in missing['futures']:
                    if row['slot']==0:row['annual_pct']=-8.9
                panel.render(dict(as_of=(NOW+pd.Timedelta(seconds=3)).isoformat(),market_overview=missing))
                APP.processEvents()
                for root in ('IF','IH','IC','IM'):
                    self.assertEqual(tuple(panel.charts[root].curve.viewRange()[1]),(-9.,-3.))
                # Only the breached side expands, for the affected product only.
                next(r for r in missing['futures'] if r['root']=='IH' and r['slot']==0)['annual_pct']=-9.5
                panel.render(dict(as_of=(NOW+pd.Timedelta(seconds=6)).isoformat(),market_overview=missing))
                APP.processEvents()
                self.assertEqual(tuple(panel.charts['IH'].curve.viewRange()[1]),(-11.5,-3.))
                detail.select('IH');self.assertEqual(tuple(detail.curve.viewRange()[1]),(-11.5,-3.))
                self.assertEqual(tuple(panel.charts['IF'].curve.viewRange()[1]),(-9.,-3.))
                # A new Shanghai day starts with that day's visible minimum and maximum.
                fresh=deepcopy(market)
                for row in fresh['futures']:row['annual_pct']=(-4.,-3.8,-3.5,-3.)[row['slot']]
                panel.render(dict(as_of=(NOW+pd.Timedelta(days=1)).isoformat(),market_overview=fresh))
                APP.processEvents()
                for root in ('IF','IH','IC','IM'):
                    self.assertEqual(tuple(panel.charts[root].curve.viewRange()[1]),(-6.,-1.))
                    detail.select(root);self.assertEqual(tuple(detail.curve.viewRange()[1]),(-6.,-1.))
            finally:panel.close();APP.processEvents()


if __name__=='__main__':unittest.main()
