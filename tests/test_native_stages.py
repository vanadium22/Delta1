import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dashboard.build_public_repository import source_files,build_repository,export_git_bundle
from dashboard.release_profiles import profile,restrict_bundle
from dashboard.native.publication import write_publication
from tests.test_native_editions import full_bundle


class StagedDeliveryTests(unittest.TestCase):
    def test_resume_preserves_completed_batches_and_rejects_changed_inputs(self):
        from dashboard.build_stage_releases import build_all
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch=root/"output/batch";batch.mkdir(parents=True)
            completed=batch/"release_manifest.json";completed.write_text("original",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"incomplete batch"):
                build_all(output_root=batch.parent,resume=batch)
            self.assertEqual(completed.read_text(encoding="utf-8"),"original")
            completed.unlink()
            (batch/"build_progress.json").write_text(json.dumps({"input_sha256":"original"}),encoding="utf-8")
            source=root/"runtime/stage_inputs/batch/demo.json";source.parent.mkdir(parents=True)
            source.write_text("changed",encoding="utf-8")
            with patch("dashboard.build_stage_releases.ROOT",root):
                with self.assertRaisesRegex(ValueError,"input has changed"):
                    build_all(output_root=batch.parent,resume=batch)

    def test_sources_are_compiled_to_scope_not_runtime_mode_switches(self):
        for stage in ("50","80","100"):
            files,_=source_files(stage=stage)
            view=files["dashboard/native/market_view.py"].decode()
            settings=files["dashboard/native/presentation.py"].decode()
            self.assertNotIn("SHOW_DETAIL",view);self.assertNotIn("SHOW_EVENTS",view)
            self.assertNotIn("release_profiles",str(files))
            self.assertEqual("class SpecialIndicatorsPage" in view,stage!="50")
            self.assertEqual("class MarketEventsPage" in view,stage!="50")
            self.assertEqual("def select_event" in view,stage=="100")
            self.assertEqual("def build_details" in view,stage=="100")
            self.assertNotIn("SHOW_DETAIL",settings)
            self.assertEqual("dashboard/native/basis_panel.py" in files,stage=="100")

    def test_snapshot_projection_preserves_common_metrics_and_removes_extra_data(self):
        original=full_bundle(True)
        for view in original["views"].values():
            view["pair_research"]={"version":"basis_pairs_v1","basis":[]}
            view["analytics"]={"calendar_bp":10.,"beta":.8,"residual_z":3.}
            view["events"]=[{"event_time":"2026-09-30T02:00:00Z","product":"IC","type":"basis","title":"偏离",
                             "value":3.,"peak":4.,"duration":5,"lifecycle":"active","status":"observed"}]
        for stage,count in (("50",4),("80",8),("100",12)):
            bundle=restrict_bundle(original,stage)
            self.assertEqual(len(bundle["views"]),count)
            self.assertEqual(bundle["snapshot_id"],original["snapshot_id"])
            state=bundle["views"]["IC:1m"]
            self.assertEqual(state["values"]["basis_bp"],-10.)
            self.assertEqual(state["analytics"]["calendar_bp"],10.)
            if stage=="50":
                self.assertEqual(state["factors"],[]);self.assertEqual(state["events"],[])
                self.assertEqual(set(state["analytics"]),{"calendar_bp"})
            if stage!="100":
                self.assertNotIn("regression",state["frames"])
                self.assertNotIn("pair_research",state)
            if stage=="80": self.assertNotIn("peak",state["events"][0])

    def test_distinct_scope_cannot_inherit_a_more_complete_git_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"app"
            build_repository(path,stage="100")
            before=subprocess.check_output(["git","-C",str(path),"rev-parse","HEAD"])
            with self.assertRaisesRegex(ValueError,"own Git history"): build_repository(path,stage="50")
            self.assertEqual(subprocess.check_output(["git","-C",str(path),"rev-parse","HEAD"]),before)

    def test_every_scope_clones_and_renders_with_correct_capabilities(self):
        root=Path(__file__).resolve().parents[1]
        for stage,count,rows in (("50",1,5),("80",3,8),("100",3,8)):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp);demo=write_publication(folder/"input",full_bundle(True))
                repository=build_repository(folder/"export",demo_path=demo,stage=stage)
                bundle=export_git_bundle(repository,folder/"delivery.bundle")
                subprocess.run(["git","clone",str(bundle),str(folder/"clone")],check=True,capture_output=True)
                script=f'''
import os,time
os.environ['QT_QPA_PLATFORM']='offscreen'
from dashboard.native.bootstrap import configure_qt
configure_qt()
from PySide6.QtWidgets import QApplication
from dashboard.native.shell import Window,configure_style
from dashboard.native.publication import MarketFeed
app=QApplication([]);configure_style(app)
model=MarketFeed('dashboard/data');window=Window(model,demo=True);window.show()
deadline=time.monotonic()+15
while window.state is None and time.monotonic()<deadline:
    app.processEvents();time.sleep(.01)
assert window.state is not None,window.status.text()
assert window.pages.count()=={count}
assert window.dashboard.matrix.rowCount()=={rows}
assert window.refresh_timer.isActive()=={stage=='100'}
assert hasattr(window,'term_chart')=={stage=='100'}
assert hasattr(window,'factor_table')=={stage!='50'}
for p,c in window.dashboard.product_checks.items(): c.setChecked(p=='IF')
assert set(window.dashboard.comparison.lines)=={{'IF'}}
for i in range({count}): window.navigate(i);app.processEvents()
window.close();app.processEvents()
'''
                env={**os.environ,"QT_QPA_PLATFORM":"offscreen","PYTHONPATH":str(root/".deps/dashboard_native")}
                result=subprocess.run([sys.executable,"-B","-X","utf8","-c",script],cwd=folder/"clone",env=env,
                    capture_output=True,text=True,encoding="utf-8",timeout=25)
                self.assertEqual(result.returncode,0,result.stderr)


if __name__=="__main__": unittest.main()
