"""Dated App refresh and readable settings with unchanged credential storage."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from dashboard.marketdata import history_maintenance as hm
from dashboard.marketdata.ddb_connection import app_endpoint,connection_summary,with_endpoint
from dashboard.native.overview_status import data_dates,dates_text
from tests import test_app_pipeline as pipeline_tests

APP=pipeline_tests.APP
pump=pipeline_tests.pump


class DdbEndpointTests(unittest.TestCase):
    def test_current_endpoint_is_separate_from_protected_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'connection.json'
            raw=b'{"host":"old.invalid","port":8848,"protected_credentials":{"scheme":"fixture","payload":"PRIVATE_PASSWORD"}}'
            path.write_bytes(raw)
            config=dict(history_connection_file=str(path))
            result=connection_summary(config)
            self.assertEqual((result['host'],result['port']),('192.168.198.77',8904))
            self.assertEqual((result['saved_host'],result['saved_port']),('old.invalid',8848))
            self.assertFalse(result['saved_endpoint_matches']);self.assertFalse(result['network_tested'])
            self.assertNotIn('PRIVATE_PASSWORD',json.dumps(result));self.assertEqual(path.read_bytes(),raw)

    def test_explicit_app_endpoint_preserves_provider_options_and_validates_pair(self):
        config=dict(history_ddb_host='custom.invalid',history_ddb_port='9001')
        endpoint=app_endpoint(config)
        original=dict(host='old.invalid',port=8848,username='PRIVATE_USER',password='PRIVATE_PASSWORD',enable_ssl=True,extra=17)
        selected=with_endpoint(original,endpoint)
        self.assertEqual((selected['host'],selected['port']),('custom.invalid',9001))
        self.assertEqual((original['host'],original['port']),('old.invalid',8848))
        for key in ('username','password','enable_ssl','extra'):self.assertEqual(selected[key],original[key])
        for bad in (dict(history_ddb_host='https://bad'),dict(history_ddb_host='ok',history_ddb_port=0),
                    dict(history_ddb_host='ok',history_ddb_port='8904?')):
            with self.assertRaises((ValueError,TypeError)):app_endpoint(bad)

    def test_real_adapter_uses_same_credentials_at_selected_endpoint(self):
        session=Mock();session.connect.return_value=True
        module=SimpleNamespace(session=Mock(return_value=session))
        secret=dict(host='old.invalid',port=8848,username='PRIVATE_USER',password='PRIVATE_PASSWORD',enable_ssl=True)
        with patch('index_strategy.history.credentials.load_config',return_value=secret),\
             patch.object(hm.socket,'create_connection') as tcp,patch.dict(sys.modules,dolphindb=module):
            client=hm.open_direct('fixture.json',endpoint=app_endpoint({}));client.close()
        tcp.assert_called_once_with(('192.168.198.77',8904),timeout=3)
        session.connect.assert_called_once_with('192.168.198.77',8904,'PRIVATE_USER','PRIVATE_PASSWORD',readTimeout=15,writeTimeout=10)
        self.assertEqual(secret['host'],'old.invalid');session.close.assert_called_once()

    def run_gap(self,factory,*,auto=False):
        from tests.test_overview_percentiles import metadata
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        reference=root/'reference.json';reference.write_text('{}')
        config=dict(reference_file=str(reference),history_roots=[str(root/'history')],history_connection_file=str(root/'credentials.json'))
        secret=dict(host='old.invalid',port=8848,username='PRIVATE_USER',password='PRIVATE_PASSWORD',enable_ssl=True)
        with ExitStack() as stack:
            stack.enter_context(patch.object(hm,'latest_contracts',return_value=metadata()))
            stack.enter_context(patch('dashboard.marketdata.repository.MarketDataRepository'))
            stack.enter_context(patch('dashboard.marketdata.overview_percentiles.requirements',return_value=dict(start='2026-08-10',end='2026-11-09',mapping_gaps=[])))
            stack.enter_context(patch('dashboard.marketdata.overview_daily.seed_local',return_value=0))
            stack.enter_context(patch('dashboard.marketdata.overview_http_closes.collect',return_value=dict(status='no_verified_closes',inserted=0)))
            stack.enter_context(patch('dashboard.marketdata.overview_daily.requests',return_value=[dict(day='2026-11-10',asset='future',symbols=['IF2611.CFE'],requires_oi=True)]))
            fill=stack.enter_context(patch('dashboard.marketdata.overview_daily.fill',return_value=dict(status='complete',target='2026-11-10',inserted=1,pending_rows=0,pending_batches=0)))
            stack.enter_context(patch('index_strategy.history.credentials.load_config',return_value=secret))
            vpn=Mock()
            def ensure(connection,*args,**kwargs):
                vpn.selected=dict(connection)
                return dict(state='connected',mode='existing_route',tcp_verified=True)
            vpn.side_effect=ensure
            stack.enter_context(patch('dashboard.marketdata.ddb_vpn.ensure_connected',vpn))
            stack.enter_context(patch.object(hm,'open_direct',factory))
            result=hm._run_overview_cycle(root,config,budget=45,stop_file=None,direct_factory=factory,lifetime=None,
                vpn_mode='auto' if auto else 'manual',include_completed_today=True,now='2026-11-11T08:30:00+08:00')
        return result,fill,vpn,secret

    def test_preopen_nov11_uses_nov10_and_same_endpoint_for_route_and_database(self):
        client=Mock();factory=Mock(return_value=client)
        result,fill,vpn,secret=self.run_gap(factory,auto=True)
        self.assertEqual(result['target'],'2026-11-10');self.assertEqual(result['state'],'complete')
        self.assertEqual(factory.call_args.kwargs['endpoint']['port'],8904)
        self.assertEqual(vpn.selected['host'],'192.168.198.77')
        self.assertEqual(vpn.selected['password'],'PRIVATE_PASSWORD')
        self.assertEqual(secret['host'],'old.invalid');fill.assert_called_once();client.close.assert_called_once()
        self.assertNotIn('PRIVATE_',json.dumps(result));self.assertEqual(result['ddb_connection']['stage'],'complete')

    def test_connection_failure_is_not_a_false_complete_or_dividend_failure(self):
        factory=Mock(side_effect=hm.DDBConnectionError('tcp'))
        result,fill,vpn,_=self.run_gap(factory)
        self.assertEqual(result['state'],'waiting_network');self.assertEqual(result['target'],'2026-11-10')
        self.assertEqual(result['ddb_connection']['stage'],'tcp');self.assertEqual(result['inserted'],0)
        self.assertIn('公盘独立更新',result['message']);fill.assert_not_called();vpn.assert_not_called()


class SettingsLayoutTests(unittest.TestCase):
    def fixture(self):
        helper=pipeline_tests.PipelineTests();window,pipeline=helper.fixture();self.addCleanup(helper.doCleanups)
        window.refresh=Mock();window.state={}
        def save(config):
            pipeline.model.config=dict(config)
            (pipeline.model.local_root/'native.json').write_text(json.dumps(config))
        pipeline.model.save_config=Mock(side_effect=save)
        def submit(fn,done):
            try:value=fn()
            except Exception as exc:value=dict(failed=True,error_type=type(exc).__name__)
            done(value);return True
        pipeline.submit=Mock(side_effect=submit)
        return window,pipeline

    def test_expanded_fields_scroll_at_three_sizes_without_expanding_window(self):
        from dashboard.native.data_pipeline import PipelinePage
        from dashboard.native.card_style import CARD_STYLE
        window,pipeline=self.fixture();window.setStyleSheet(CARD_STYLE)
        page=PipelinePage(pipeline);window.setCentralWidget(page);page.settings.body.show()
        for width,height in ((1920,1080),(1536,864),(860,620)):
            window.resize(width,height);window.show();pump(.03)
            self.assertEqual((window.width(),window.height()),(width,height))
            self.assertGreater(page.scroll_area.verticalScrollBar().maximum(),0)
            for field in page.settings.fields.values():
                self.assertGreaterEqual(field.height(),40);self.assertGreaterEqual(field.width(),160)
            rectangles=[b.geometry() for b in page.buttons]
            for i,a in enumerate(rectangles):
                for b in rectangles[i+1:]:self.assertFalse(a.intersects(b))
        window.close()

    def test_endpoint_only_save_never_reads_or_rewrites_credentials(self):
        from dashboard.native.inline_settings import InlineSettings
        window,pipeline=self.fixture();path=pipeline.model.local_root/'credentials.json'
        raw=b'{"protected_credentials":{"payload":"PRIVATE_CIPHER"}}';path.write_bytes(raw)
        pipeline.model.config['history_connection_file']=str(path)
        widget=InlineSettings(pipeline);self.addCleanup(widget.deleteLater)
        with patch('index_strategy.history.credentials.provider',side_effect=AssertionError('credential write')),\
             patch('index_strategy.history.credentials.load_config',side_effect=AssertionError('credential read')):
            widget.fields['host'].setText('192.168.198.77');widget.fields['port'].setText('8904');widget.save_endpoint()
        self.assertEqual(path.read_bytes(),raw)
        self.assertEqual(pipeline.model.config['history_ddb_host'],'192.168.198.77')
        self.assertEqual(pipeline.model.config['history_ddb_port'],8904)
        self.assertNotIn('password',pipeline.model.config);self.assertFalse(window.busy)

    def test_invalid_address_cannot_start_a_write_or_clear_protected_password(self):
        from dashboard.native.inline_settings import InlineSettings
        window,pipeline=self.fixture();widget=InlineSettings(pipeline);self.addCleanup(widget.deleteLater)
        widget.fields['port'].setText('8904?');widget.save_endpoint()
        pipeline.submit.assert_not_called();pipeline.model.save_config.assert_not_called()
        self.assertFalse(window.busy)

    def test_unreadable_old_password_is_preserved_when_saving_credentials(self):
        from dashboard.native.inline_settings import InlineSettings
        window,pipeline=self.fixture();path=pipeline.model.local_root/'credentials.json'
        raw=b'{"protected_credentials":{"payload":"PRIVATE_CIPHER"}}';path.write_bytes(raw)
        pipeline.model.config['history_connection_file']=str(path)
        widget=InlineSettings(pipeline);self.addCleanup(widget.deleteLater)
        widget.fields['username'].setText('PRIVATE_USER')
        provider=Mock();provider.load_config.side_effect=PermissionError('PRIVATE_EXCEPTION')
        with patch('index_strategy.history.credentials.provider',return_value=provider):widget.save_credentials()
        self.assertEqual(path.read_bytes(),raw);provider.save_config.assert_not_called()
        pipeline.model.save_config.assert_not_called();self.assertNotIn('PRIVATE_',widget.notice.text())


class DataDateTests(unittest.TestCase):
    def test_preopen_price_and_target_nov10_are_distinct_from_y_dividend_nov6(self):
        data=dict(completed_session='2026-11-10',dividend_latest_business_day='2026-11-06',
            indices=[dict(price=4000,source_at='2026-11-10T15:00:00+08:00')],futures=[])
        value=data_dates(data)
        self.assertEqual(value,dict(price_days=['2026-11-10'],completed_target='2026-11-10',dividend_day='2026-11-06'))
        self.assertIn('价格数据日：2026-11-10',dates_text(value))
        self.assertIn('最新分红表（公盘）：2026-11-06',dates_text(value))

    def test_mixed_price_days_and_invalid_clocks_do_not_claim_all_current(self):
        data=dict(indices=[dict(price=4000,source_at='2026-11-06T15:00:00+08:00'),dict(price=4001,source_at='2026-11-10T15:00:00+08:00'),
            dict(price=2,source_at='bad-clock')])
        value=data_dates(data,'2026-11-10')
        self.assertEqual(value['price_days'],['2026-11-06','2026-11-10'])
        self.assertIn('2026-11-06～2026-11-10',dates_text(value))

    def test_overview_summary_names_price_and_dividend_sources(self):
        from tests.test_market_overview_ui import state
        from dashboard.native.overview_summary import OverviewSummary
        widget=OverviewSummary();self.addCleanup(widget.deleteLater)
        data=state()['market_overview'];data.update(completed_session='2026-11-10',dividend_latest_business_day='2026-11-06')
        for row in [*data['indices'],*data['futures']]:row['source_at']='2026-11-10T15:00:00+08:00'
        widget.render_data(data)
        self.assertIn('价格数据日：2026-11-10',widget.dividend_source.text())
        self.assertIn('最新分红表（公盘）：2026-11-06',widget.dividend_source.text())


if __name__=='__main__':unittest.main()
