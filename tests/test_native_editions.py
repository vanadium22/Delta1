"""Edition capability boundaries and developer-to-viewer synchronization."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import subprocess
import sys
import zipfile
from unittest.mock import patch

import pandas as pd

from dashboard.native.publication import (PRODUCTS,FREQUENCIES,ViewerModel,empty_state,
    encode_state,make_bundle,write_publication)
from dashboard.native.developer_model import DeveloperModel
from dashboard.native.startup import instance_name


def synthetic_state(product="IC",frequency="1m",demo=False):
    state=empty_state({"product":product,"frequency":frequency,"demo":demo})
    state.pop("publication_error");state.pop("publication_stale")
    frame=pd.DataFrame([{"event_time":pd.Timestamp("2026-09-30T02:00:00Z"),
        "trade_date":pd.Timestamp("2026-09-30").date(),"session_id":"am","close":7000.,"value":15.}])
    state.update(spread=frame,basis=frame,near=frame,spot=frame,versions={"fixture":"1"})
    state["values"].update(spread=15.,basis_bp=-10.,zscore=2.2)
    state["factors"]=[{"spec":{"id":"alpha","name":"观察指标","version":"v1","unit":"bp",
        "inputs":[{"frequency":"1m","dataset_id":"private-dataset"}],"code":"PRIVATE_FORMULA_CODE","params":{"private":1}},
        "values":{"x":42.},"quality":"research","error":"P:/private/secret.txt"}]
    state["errors"]=["P:/private/secret.txt"]
    return state


def full_bundle(demo=False):
    return make_bundle([synthetic_state(p,f,demo) for p in PRODUCTS for f in FREQUENCIES],demo)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.viewer=ViewerModel(self.root/"published",self.root/"viewer-settings")
        self.request={"product":"IC","frequency":"1m"}

    def test_missing_publication_does_not_create_config_or_result_directories(self):
        result=self.viewer.snapshot(self.request)
        self.assertTrue(result["publication_stale"])
        self.assertEqual(list(self.root.iterdir()),[])
        for operation in (self.viewer.save_config,self.viewer.publish_formula,self.viewer.preview,self.viewer.archive):
            with self.assertRaises(PermissionError): operation({})

    def test_all_profiles_roundtrip_without_private_fields(self):
        bundle=full_bundle();write_publication(self.viewer.publish_root,bundle)
        text=(self.viewer.publish_root/"current.json").read_text(encoding="utf-8")
        for secret in ("PRIVATE_FORMULA_CODE","P:/private","private-dataset",'"params"','"code"'):
            self.assertNotIn(secret,text)
        for product in PRODUCTS:
            for frequency in FREQUENCIES:
                result=self.viewer.snapshot({"product":product,"frequency":frequency,"save":True})
                self.assertEqual((result["product"],result["frequency"]),(product,frequency))
                self.assertEqual(result["spread"].iloc[-1]["value"],15.)
                self.assertTrue(pd.api.types.is_datetime64_any_dtype(result["near"].event_time))
        self.assertFalse(self.viewer.local_root.exists())

    def test_new_published_formula_appears_without_restarting_reader(self):
        bundle=full_bundle();write_publication(self.viewer.publish_root,bundle)
        self.viewer.snapshot(self.request)
        bundle["snapshot_id"]="new-version"
        item=deepcopy(bundle["views"]["IC:1m"]["factors"][0]);item["spec"]["id"]="new_factor"
        bundle["views"]["IC:1m"]["factors"].append(item)
        write_publication(self.viewer.publish_root,bundle)
        result=self.viewer.auto_snapshot(self.request)
        self.assertIn("new_factor",[f["spec"]["id"] for f in result["factors"]])
        self.assertIsNone(self.viewer.auto_snapshot(self.request))

    def test_four_product_cache_uses_one_generation_without_ui_disk_reads(self):
        bundle=full_bundle();bundle["views"]["IF:1m"]["values"]["basis_bp"]=123.
        write_publication(self.viewer.publish_root,bundle)
        self.viewer.snapshot(self.request)
        with patch.object(Path,"read_text",side_effect=AssertionError("UI must not read publication files")):
            group=self.viewer.market_states("1m")
        self.assertEqual(set(group),set(PRODUCTS))
        self.assertEqual(group["IF"]["values"]["basis_bp"],123.)
        self.assertEqual(len({s["publication_id"] for s in group.values()}),1)
        invalid=full_bundle();invalid["views"]["IH:1m"]["values"]["basis_bp"]="invalid"
        write_publication(self.viewer.publish_root,invalid)
        result=self.viewer.snapshot(self.request)
        self.assertTrue(result["publication_stale"])
        self.assertEqual(self.viewer.market_states("1m")["IF"]["values"]["basis_bp"],123.)

    def test_offline_demo_does_not_require_live_publisher_heartbeat(self):
        bundle=full_bundle(True);bundle["heartbeat_at"]="2020-01-01T00:00:00Z"
        write_publication(self.viewer.publish_root,bundle)
        self.assertFalse(self.viewer.snapshot({**self.request,"demo":True})["publication_stale"])

    def test_stale_corrupt_and_incompatible_publication_preserve_last_good_result(self):
        bundle=full_bundle();write_publication(self.viewer.publish_root,bundle)
        self.viewer.snapshot(self.request)
        bundle["heartbeat_at"]="2020-01-01T00:00:00Z";write_publication(self.viewer.publish_root,bundle)
        self.assertTrue(self.viewer.auto_snapshot(self.request)["publication_stale"])
        path=self.viewer.publish_root/"current.json";path.write_text("{broken",encoding="utf-8")
        result=self.viewer.snapshot(self.request)
        self.assertEqual(result["values"]["spread"],15.);self.assertTrue(result["publication_stale"])
        invalid=full_bundle();invalid["views"]["IC:1m"]["values"]["spread"]="bad-number"
        write_publication(self.viewer.publish_root,invalid)
        result=self.viewer.snapshot(self.request)
        self.assertEqual(result["values"]["spread"],15.);self.assertTrue(result["publication_stale"])
        bundle["schema_version"]="unsupported";write_publication(self.viewer.publish_root,bundle)
        self.assertIn("更新",self.viewer.snapshot(self.request)["publication_error"])

    def test_demo_cannot_replace_real_publication(self):
        write_publication(self.viewer.publish_root,full_bundle(False))
        write_publication(self.viewer.publish_root,full_bundle(True))
        self.assertFalse(self.viewer.snapshot(self.request)["demo"])
        self.assertTrue(self.viewer.snapshot({**self.request,"demo":True})["demo"])

    def test_failed_atomic_replace_keeps_previous_file(self):
        write_publication(self.viewer.publish_root,full_bundle())
        path=self.viewer.publish_root/"current.json";before=path.read_bytes()
        with patch("dashboard.native.publication.os.replace",side_effect=OSError("locked")):
            with self.assertRaises(OSError): write_publication(self.viewer.publish_root,full_bundle())
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(list(self.viewer.publish_root.glob("*.tmp")),[])

    def test_expired_book_is_removed_even_while_publisher_heartbeat_is_fresh(self):
        bundle=full_bundle();view=bundle["views"]["IC:1m"]
        view["book"]={"buy":1.,"sell":0.,"mid":.5};view["book_valid_until"]="2020-01-01T00:00:00Z"
        write_publication(self.viewer.publish_root,bundle)
        result=self.viewer.snapshot(self.request)
        self.assertIsNone(result["book"]);self.assertIn("过期",result["book_reason"])

    def test_editions_have_distinct_single_instance_channels(self):
        self.assertNotEqual(instance_name(self.root,edition="developer"),instance_name(self.root,edition="viewer"))


class DeveloperPublishTests(unittest.TestCase):
    def test_formula_change_publishes_all_profiles_and_replay_does_not_overwrite(self):
        from tests.test_native_dashboard import fixture
        from dashboard.native.factors import TEMPLATES
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=fixture(root/"data")
            model=DeveloperModel(root/"settings",root/"published")
            try:
                model.config.update(history_roots=[str(data.root)],results_root=str(root/"results"))
                request={"product":"IC","frequency":"1m","save":False}
                state=model.snapshot(request);self.assertNotIn("publish_error",state)
                viewer=ViewerModel(root/"published")
                self.assertAlmostEqual(viewer.snapshot(request)["values"]["spread"],state["values"]["spread"])
                payload=json.loads((root/"published/current.json").read_text(encoding="utf-8"))
                self.assertEqual(len(payload["views"]),12)
                model.publish_formula({**TEMPLATES[0],"id":"future_development","name":"后续新增指标",
                    "code":"def compute(inputs, params):\n    return {'新增值': 123.0}\n"})
                model.auto_snapshot(request)
                result=viewer.auto_snapshot(request)
                factor=next(x for x in result["factors"] if x["spec"]["id"]=="future_development")
                self.assertEqual(factor["values"]["新增值"],123.)
                before=(root/"published/current.json").read_bytes()
                model.snapshot({**request,"as_of":"2026-09-30T02:00:00Z"})
                self.assertEqual((root/"published/current.json").read_bytes(),before)
            finally: model.close()


class EditionQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"]="offscreen"
        from dashboard.native.bootstrap import configure_qt
        configure_qt()
        from PySide6.QtWidgets import QApplication
        from dashboard.native.app import configure_style
        cls.app=QApplication.instance() or QApplication([]);configure_style(cls.app)

    def test_viewer_constructs_only_shared_dashboard_and_no_developer_controls(self):
        from dashboard.native.public_app import Window
        from dashboard.native.market_view import MarketOverviewPage
        from PySide6.QtWidgets import QPushButton
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_publication(root/"published",full_bundle())
            viewer=ViewerModel(root/"published",root/"viewer")
            window=Window(viewer);window.show()
            try:
                end=time.monotonic()+10
                while window.state is None and time.monotonic()<end:
                    self.app.processEvents();time.sleep(.01)
                self.assertIsNotNone(window.state)
                self.assertIsInstance(window.dashboard,MarketOverviewPage)
                self.assertEqual(window.pages.count(),3)
                for name in ("publish_formula","collect_start","collect_once","save_settings"):
                    self.assertIsNone(window.findChild(QPushButton,name))
                self.assertFalse(hasattr(window,"code"));self.assertFalse(hasattr(window,"save_replay"))
                self.assertFalse(window.request()["save"])
                window.navigate(1);self.assertEqual(window.pages.currentIndex(),1)
                window.navigate(2);self.assertEqual(window.pages.currentIndex(),2)
                self.assertFalse(viewer.local_root.exists())
                self.assertGreater(window.factor_table.rowCount(),0)
                self.assertEqual(window.dashboard.matrix.rowCount(),8)
            finally:
                window.close()
                end=time.monotonic()+10
                while window.isVisible() and time.monotonic()<end:
                    self.app.processEvents();time.sleep(.01)


class DistributionTests(unittest.TestCase):
    def test_package_reuses_current_shared_code_and_runs_without_developer_modules(self):
        from dashboard.build_viewer_package import build
        from dashboard.build_public_repository import ROOT,SHARED_FILES,EXPORT_NAMES,public_python
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package=build(root/"viewer.zip")
            with zipfile.ZipFile(package) as archive:
                names=archive.namelist()
                for blocked in ("collection.py","model.py","developer_model.py","factor_worker.py","factors.py","demo.py","native.json"):
                    self.assertFalse(any(n.endswith("/"+blocked) for n in names),blocked)
                for name in SHARED_FILES:
                    path="dashboard/native/"+EXPORT_NAMES.get(name,name)
                    self.assertEqual(archive.read(path),public_python(name))
                archive.extractall(root/"unpacked")
            env={**os.environ,"QT_QPA_PLATFORM":"offscreen","PYTHONPATH":str(ROOT.parent/".deps/dashboard_native")}
            env.pop("SWHY_DELTA1_PUBLISH_ROOT",None)
            command=[sys.executable,"-B","-s","-X","utf8","-m","dashboard"]
            result=subprocess.run([*command,"--startup-check"],cwd=root/"unpacked",env=env,capture_output=True,text=True,encoding="utf-8",timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            denied=subprocess.run([*command,"--edition","developer"],cwd=root/"unpacked",env=env,capture_output=True,text=True,encoding="utf-8",timeout=10)
            self.assertEqual(denied.returncode,2)

    def test_retired_editions_no_longer_launch_from_default_entry(self):
        project=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            env={**os.environ,"QT_QPA_PLATFORM":"offscreen"}
            for edition in ('developer','viewer'):
                result=subprocess.run([sys.executable,'-B','-s','-X','utf8','-m','dashboard',
                    '--local-root',tmp,'--edition',edition,'--startup-check'],
                    cwd=project,env=env,capture_output=True,text=True,encoding='utf8',timeout=20)
                self.assertEqual(result.returncode,2)
                self.assertIn('unrecognized arguments',result.stderr)



if __name__=="__main__": unittest.main()
