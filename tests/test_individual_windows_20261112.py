"""Independent chart windows, persistence, shared reads and compact card."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dashboard.native.bootstrap import configure_qt
configure_qt()
from PySide6.QtWidgets import QApplication

from dashboard.marketdata.indicator_analysis import (CHARTS, SERIES, aggregate_selection,
    chart_selections, display_charts, draw_summary, plan, point, selection, statistics, summary)
from dashboard.native.futures_overview_view import FuturesCard
from dashboard.native.indicator_analysis_view import IndicatorAnalysisPage, seconds
from tests.test_indicator_analysis import DAY, preview
import tests.test_indicator_analysis as indicator_fixture
from tests.test_market_overview_ui import state
from tests.test_overview_percentiles import metadata

APP=QApplication.instance() or QApplication([])


def request():
    result=selection()
    result['charts']={
        'adjusted':dict(window=30,stats=7),
        'annual':dict(window=60,stats=12),
        'calendar_03_02':dict(window=90,stats=20),
        'calendar_02_01':dict(window=120,stats=25),
    }
    result.update(result['charts']['adjusted'])
    return result


class IndividualWindowTests(unittest.TestCase):
    def test_each_chart_slices_its_own_window_and_uses_its_own_statistics(self):
        choice=request();planned=plan(DAY,aggregate_selection(choice),metadata())
        history={key:[point(day,['synthetic'],value=float(date.fromisoformat(day).toordinal()%47))
                      for day in planned['days']] for key in SERIES}
        current={key:point(DAY,['synthetic'],value=20.) for key in SERIES}
        result=display_charts(planned,history,current,choice)
        self.assertEqual(result['selection'],choice)
        for key,channels in CHARTS.items():
            chosen=choice['charts'][key];info=result['charts'][key]
            self.assertEqual(info['start'],str(date.fromisoformat(DAY)-timedelta(days=chosen['window']-1)))
            self.assertEqual(len(info['reference_days']),chosen['stats'])
            self.assertNotIn(DAY,info['reference_days'])
            for channel in channels:
                actual=result['series'][channel]
                self.assertEqual(actual['statistics'],statistics(history[channel],info['reference_days'],current[channel]))
                self.assertTrue(all(info['start']<=row['day']<=DAY for row in actual['rows']))
        safe=summary(result)
        self.assertEqual(safe['selection']['charts'],choice['charts'])
        event=draw_summary(dict(interval_ms=30000,last_draw=dict(selection=choice,reason='manual')))
        self.assertEqual(event['last_draw']['selection']['charts'],choice['charts'])

    def test_invalid_or_incomplete_chart_windows_are_rejected(self):
        for mutate in (lambda c:c.pop('annual'),lambda c:c['annual'].update(stats=1),
                       lambda c:c['annual'].update(extra='private')):
            choice=request();mutate(choice['charts'])
            with self.assertRaises(ValueError):chart_selections(choice)

    def test_live_engine_uses_one_shared_read_and_reuses_the_union_cache(self):
        case=indicator_fixture.IndicatorReaderTests();case.setUp()
        try:
            choice=request();first=case.engine.snapshot(choice,**case.args)
            calls=case.repo.read_window.call_count
            self.assertGreater(calls,0)
            self.assertEqual(first['selection'],choice)
            changed=deepcopy(choice);changed['charts']['annual']['window']=50
            second=case.engine.snapshot(changed,**case.args)
            self.assertTrue(second['cache_hit'])
            self.assertEqual(case.repo.read_window.call_count,calls)
            self.assertNotEqual(first['charts']['annual']['start'],second['charts']['annual']['start'])
            self.assertEqual(first['charts']['calendar_02_01'],second['charts']['calendar_02_01'])
        finally:case.doCleanups()

    def test_history_worker_requests_the_union_of_all_four_windows(self):
        from dashboard.native.history_maintenance import HistoryMaintenance
        with tempfile.TemporaryDirectory() as tmp:
            model=SimpleNamespace(local_root=Path(tmp),config={'history_roots':['fixture']},indicator_analysis_request=request())
            owner=HistoryMaintenance(model);owner.authorized=True
            with patch('dashboard.app_config.history_python',return_value='python.exe'),patch('subprocess.Popen') as spawned:
                self.assertTrue(owner.start(force=True))
                cmd=spawned.call_args.args[0]
                self.assertEqual(cmd[cmd.index('--indicator-window')+1],'120')
                self.assertEqual(cmd[cmd.index('--indicator-stats')+1],'25')

    def test_chart_header_labels_and_controls_do_not_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            page=IndicatorAnalysisPage(SimpleNamespace(local_root=Path(tmp)))
            try:
                page.resize(1480,720);page.show();APP.processEvents()
                for chart in page.charts.values():
                    self.assertLess(chart.unit.geometry().right(),chart.window_spin.geometry().left())
                    self.assertLess(chart.window_spin.geometry().right(),chart.stats.geometry().left())
                    self.assertEqual(chart.window_spin.prefix(),'t_w ')
                    self.assertEqual(chart.stats.prefix(),'t_z ')
            finally:page.close();APP.processEvents()

    def test_chart_controls_persist_independently_and_restore_legacy_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);model=SimpleNamespace(local_root=root)
            page=IndicatorAnalysisPage(model);page.resize(1480,720);page.show();APP.processEvents()
            try:
                expected=request()
                for key,values in expected['charts'].items():
                    chart=page.charts[key];chart.auto.setChecked(False)
                    chart.window_spin.setValue(values['window']);chart.stats.setValue(values['stats'])
                self.assertEqual(page.request(),expected)
                saved=json.loads((root/'indicator_ui.json').read_text(encoding='utf8'))
                self.assertEqual(saved['chart_settings']['annual'],dict(window=60,stats=12,automatic=False))
                page.root.setCurrentIndex(2)
                other=IndicatorAnalysisPage(model)
                try:
                    self.assertEqual(other.root.currentData(),'IC')
                    for key,values in expected['charts'].items():
                        chart=other.charts[key]
                        self.assertEqual((chart.window_spin.value(),chart.stats.value()),(values['window'],values['stats']))
                        self.assertFalse(chart.auto.isChecked())
                    result=preview(other.request());other.render(result)
                    for key,chart in other.charts.items():
                        scope=result['charts'][key]
                        for line in chart.reference_lines.values():
                            self.assertEqual(list(line.getData()[0]),[seconds(scope['start']),seconds(scope['end'])])
                finally:other.close()
            finally:page.close();APP.processEvents()
            (root/'indicator_ui.json').write_text(json.dumps(dict(root='IH',slot=2,window=30,stats=17,automatic=False)),encoding='utf8')
            legacy=IndicatorAnalysisPage(model)
            try:
                for chart in legacy.charts.values():
                    self.assertEqual((chart.window_spin.value(),chart.stats.value(),chart.auto.isChecked()),(30,17,False))
            finally:legacy.close();APP.processEvents()

    def test_freeze_keeps_each_chart_window_and_never_writes_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            page=IndicatorAnalysisPage(SimpleNamespace(local_root=Path(tmp)))
            try:
                result=preview(request());page.freeze(result);page.set_active(True)
                self.assertEqual(page.request(),request())
                self.assertIsNone(page.model.indicator_analysis_request)
                self.assertTrue(all(not c.window_spin.isEnabled() and not c.stats.isEnabled() for c in page.charts.values()))
                self.assertFalse((Path(tmp)/'indicator_ui.json').exists())
                self.assertIsNotNone(page.charts['annual'].result)
            finally:page.close();APP.processEvents()

    def test_compact_card_displays_current_natural_days_and_smaller_price(self):
        row=deepcopy(state()['market_overview']['futures'][0]);row.update(days=25,price=3980.82)
        card=FuturesCard(None,compact=True)
        try:
            card.render(row,0)
            self.assertEqual(card.remaining.text(),'剩余 25 天')
            self.assertIn('IF 00',card.badge.text())
            self.assertIn('font-size:22px',card.price.styleSheet())
            self.assertIn('font-size:24px',card.badge.styleSheet())
            row['days']=None;card.render(row,0);self.assertEqual(card.remaining.text(),'剩余 —')
        finally:card.close();APP.processEvents()


if __name__=='__main__':unittest.main()
