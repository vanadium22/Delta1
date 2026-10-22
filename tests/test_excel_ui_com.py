"""Opt-in background Excel controls: never display or attach to user windows."""
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
import uuid

from dashboard.indicator_workspace import evaluate
from dashboard.indicator_ui import input_label, family_title
from dashboard.numeric_snapshot import save_snapshot
from dashboard.numeric_view import add_research_view
from tests.indicator_frozen_fixture import FrozenIndicatorModel, OBSERVED_AT

ROOT=Path(__file__).resolve().parents[1]
NAMES={'basis':'期现','calendar':'同品种跨期','cross':'跨品种'}


@unittest.skipUnless(os.environ.get('RUN_EXCEL_COM')=='1','requires desktop Excel; always hidden')
class ExcelUiControlsTests(unittest.TestCase):
    def test_real_chinese_controls_migration_stale_results_and_paging(self):
        folder=ROOT/'.deps/ui_simplification/excel'/('com_'+uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        model=FrozenIndicatorModel(folder/'settings')
        selection=dict(active_page='basis',request_id='initial',pages={
            'basis':dict(variant_id='A03.mean::basis::v1',timing='日终',limit=100),
            'calendar':dict(variant_id='A03.mean::basis::v1',timing='日终'),
            'cross':dict(variant_id='A03.mean::basis::v1',timing='日终')})
        def publish(request):
            result=evaluate(model,request,OBSERVED_AT)
            feed=add_research_view(dict(ready=True),result)
            save_snapshot(feed,folder/'feed.json')
            return feed
        publish(selection)
        stdout=(folder/'stdout.log').open('wb');stderr=(folder/'stderr.log').open('wb')
        process=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
            str(ROOT/'tests/excel_ui_probe.ps1'),'-Root',str(ROOT),'-Work',str(folder)],
            stdout=stdout,stderr=stderr,creationflags=0x08000000)
        records=[];counter=0;identity=None
        def command(page=None,edits=()):
            nonlocal counter,identity
            counter+=1
            save_snapshot(dict(id=str(counter),page=page,edits=list(edits)),folder/'command.json')
            until=time.monotonic()+35
            while time.monotonic()<until:
                if (folder/'error.txt').exists():self.fail((folder/'error.txt').read_text(encoding='utf8'))
                try:
                    r=json.loads((folder/f'response_{counter}.json').read_text(encoding='utf8'))
                    if r['id']==str(counter):
                        self.assertFalse(r['visible']);self.assertEqual(r['chart_count'],1)
                        observed=(r['hwnd'],r['full_name'])
                        if identity is None:identity=observed
                        self.assertEqual(identity,observed)
                        records.append(r);return r
                except (OSError,ValueError):pass
                if process.poll() is not None:self.fail((folder/'stderr.log').read_text(errors='replace'))
                time.sleep(.1)
            self.fail('Hidden owned workbook did not answer')
        def change(page,edits):
            name=NAMES[page];pending=command(name,edits)
            self.assertEqual(pending['pages'][name]['rows'],[])
            feed=publish(pending['request']);done=command()
            expected=feed['research']['excel_pages'][page]['summary'];actual=done['pages'][name]['rows']
            self.assertEqual(len(actual),len(expected))
            for a,e in zip(actual,expected):
                self.assertEqual(a[0],e[0]);self.assertEqual(a[2],e[2]);self.assertEqual(a[4:],e[4:])
                if e[1] is None:self.assertIsNone(a[1])
                else:self.assertAlmostEqual(a[1],e[1],places=9)
                if e[3]:
                    from dashboard.numeric_excel import excel_time
                    self.assertAlmostEqual(a[3],excel_time(e[3]),places=8)
            self.assertEqual(done['pages'][name]['nav'],"'"+name+"详情'!A1")
            return done,feed
        def edit(page,cell,value,detail=False):return dict(sheet=NAMES[page]+('详情' if detail else ''),cell=cell,value=value)
        try:
            start=command();self.assertEqual(start['pages']['期现']['limit'],24)
            publish(start['request']);command()
            for page in NAMES:
                for input_id in ('future','basis','annual'):
                    if page=='cross' and input_id=='future':continue
                    done,feed=change(page,[edit(page,'B3',family_title('A03.mean')),edit(page,'E3',input_label(input_id))])
                    self.assertEqual(done['request']['pages'][page]['variant_id'],f'A03.mean::{input_id}::v1')
                    self.assertEqual(len(done['pages'][NAMES[page]]['rows']),6 if page=='cross' else 4)
            # Rapid control changes: the intermediate response must not repopulate a new title.
            old=command('期现',[edit('basis','E3',input_label('future'))]);stale=publish(old['request'])
            newer=command('期现',[edit('basis','E3',input_label('annual'))]);self.assertEqual(newer['pages']['期现']['rows'],[])
            rejected=command();self.assertEqual(rejected['pages']['期现']['rows'],[])
            publish(newer['request']);command()
            done,_=change('basis',[edit('basis','B3','A03.std::future::v1')])
            self.assertEqual(done['pages']['期现']['input'],input_label('future'))
            self.assertEqual(done['request']['pages']['basis']['family_id'],'A03.std')
            done,_=change('basis',[edit('basis','E3','更多口径'),edit('basis','B7',input_label('log_basis'),True)])
            self.assertEqual(done['request']['pages']['basis']['variant_id'],'A03.std::log_basis::v1')
            done,_=change('cross',[edit('cross','E3',input_label('future'))])
            self.assertEqual(done['pages']['跨品种']['rows'],[]);self.assertIn('不适用',done['pages']['跨品种']['status'])
            done,_=change('cross',[edit('cross','B3',family_title('B12')),edit('cross','E5',0,True)])
            self.assertEqual(done['pages']['跨品种']['input'],'固定口径');self.assertEqual(done['pages']['跨品种']['p'],0)
            done,_=change('cross',[edit('cross','E5',None,True)])
            self.assertIsNone(done['pages']['跨品种']['p'])
            done,_=change('basis',[edit('basis','E3',input_label('basis')),edit('basis','E4','全部合约'),edit('basis','B5',4,True)])
            done,_=change('basis',[edit('basis','H4',4,True)])
            self.assertEqual(done['request']['pages']['basis']['offset'],4)
            done,_=change('basis',[edit('basis','E4','默认代表')])
            self.assertEqual(done['request']['pages']['basis']['offset'],0);self.assertEqual(len(done['pages']['期现']['rows']),4)
            self.assertIsNone(done['pages']['期现']['old_row'])
            done,_=change('basis',[edit('basis','B3',family_title('B07')),edit('basis','E3',input_label('future'))])
            self.assertEqual(done['pages']['期现']['input_validation'],input_label('future'))
            done,_=change('basis',[edit('basis','E3',input_label('annual'))])
            self.assertEqual(done['pages']['期现']['rows'],[]);self.assertIn('不适用',done['pages']['期现']['status'])
            save_snapshot(dict(passed=True,checks=records,workbook=str(folder/'verified.xlsx')),folder/'evidence.json')
            (ROOT/'.deps/ui_simplification/excel/latest_com.json').write_text(json.dumps(dict(folder=str(folder),checks=len(records),passed=True),ensure_ascii=False),encoding='utf8')
        finally:
            (folder/'stop').write_text('stop',encoding='utf8')
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
            stdout.close();stderr.close()


if __name__=='__main__':unittest.main()
