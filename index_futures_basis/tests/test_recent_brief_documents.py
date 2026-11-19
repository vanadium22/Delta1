"""Word/PDF completion, preserved previous results and native frontend actions."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PIL import Image

from index_futures_basis.desktop import Window
from index_futures_basis.service import BasisService
from index_futures_basis.recent_brief.automation import publish_latest
from index_futures_basis.recent_brief.documents import export_documents, WORD_NAME, PDF_NAME
from index_futures_basis.recent_brief.workflow import FIGURES, latest_paths, generate_for_service, repackage
from index_futures_basis.recent_brief.work_automation import register_task


class DocumentTests(unittest.TestCase):
    def test_word_pdf_and_editable_images_without_html(self):
        from docx import Document
        from index_futures_basis.recent_brief.charts import setup
        setup()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in FIGURES:
                Image.new("RGB", (380, 560), "white").save(root/name)
            info = {"as_of": "2026-01-05", "created_at": "2026-01-06", "dividend_date": "2026-01-01",
                    "summary_cards": [{"title": "偏离60日均值", "value": "+1.0 点", "detail": "当前与历史均值", "direction": 1} for _ in range(4)],
                    "explanations": ["说明"]*4, "source_note": "实际行情日期", "narrative": "当前基差与量仓的综合观察。"}
            result = export_documents(root, FIGURES, info)
            document = Document(root/WORD_NAME)
            self.assertEqual(len(document.inline_shapes), 8)
            self.assertEqual(len(document.tables), 1)
            self.assertIn("偏离60日均值", document.tables[0].cell(0, 0).text)
            text = "\n".join(p.text for p in document.paragraphs)
            self.assertNotIn("说明", text)
            self.assertNotIn("实际行情日期", text)
            self.assertLess(text.index(info["narrative"]), text.index("近期绝对基差与跨期"))
            narrative_paragraph = next(p for p in document.paragraphs if p.text == info["narrative"])
            self.assertEqual(narrative_paragraph.runs[0].font.size.pt, 15)
            pdf = (root/PDF_NAME).read_bytes()
            self.assertTrue(pdf.startswith(b"%PDF"))
            self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", pdf)), result["pages"])
            self.assertEqual(result["pages"], 9)
            self.assertTrue(all((root/name).exists() for name in FIGURES))
            self.assertEqual(list(root.glob("*.html")), [])
            from index_futures_basis.recent_brief.documents import _source
            self.assertIn('早于行情62天',_source({**info,'dividend_warning':'早于行情62天，请检查分红更新'}))

    def test_incomplete_document_does_not_replace_successful_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            success, failed = root/"success", root/"failed"
            for folder in (success, failed):
                folder.mkdir()
                (folder/"run_manifest.json").write_text(json.dumps({"as_of": "2026-01-05", "created_at": "first"}), encoding="utf-8")
                (folder/PDF_NAME).write_bytes(b"%PDF-test")
            (success/WORD_NAME).write_bytes(b"PK-test")
            publish_latest(success, root)
            before = (root/"latest.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "未完整"):
                publish_latest(failed, root)
            self.assertEqual(before, (root/"latest.json").read_bytes())
            self.assertEqual(latest_paths(root)["folder"], success.resolve())
            self.assertTrue((root/"latest.pdf").exists())
            self.assertTrue((root/"latest.docx").exists())

    def test_demo_cannot_export_real_brief(self):
        with tempfile.TemporaryDirectory() as directory:
            service = BasisService(Path(directory), "demo")
            with self.assertRaisesRegex(ValueError, "真实数据"):
                generate_for_service(service)

    def test_repackage_preserves_original_and_records_replaced_png(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root/"source", root/"revised"
            source.mkdir()
            for name in FIGURES:
                (source/name).write_bytes(b"revised image")
            manifest = {"as_of": "2026-01-05", "created_at": "original", "summary_cards": [],
                        "explanations": ["说明"]*4, "output_files": {n: {"sha256": "original hash"} for n in FIGURES}}
            raw = json.dumps(manifest)
            (source/"run_manifest.json").write_text(raw, encoding="utf-8")
            def export(output, files, info):
                (output/PDF_NAME).write_bytes(b"%PDF-test")
                (output/WORD_NAME).write_bytes(b"PK-test")
                return {"pdf": PDF_NAME, "word": WORD_NAME, "pages": 8}
            with patch("index_futures_basis.recent_brief.workflow.export_documents", side_effect=export), \
                 patch("index_futures_basis.recent_brief.workflow.ROOT", root):
                repackage(source, target)
            result = json.loads((target/"run_manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(result["document_rebuild"]["recalculated_market"])
            self.assertEqual(result["document_rebuild"]["images_changed_since_source_manifest"], FIGURES)
            self.assertEqual((source/"run_manifest.json").read_text(encoding="utf-8"), raw)
            self.assertEqual((source/FIGURES[0]).read_bytes(), (target/FIGURES[0]).read_bytes())

    def test_existing_automation_schedule_and_pause_are_preserved(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"mail_app").mkdir()
            (root/"mail_app/work.py").touch()
            project = root/"basis"
            project.mkdir()
            existing = {"id": "original-task", "program": str(project/"start_recent_brief_daily.cmd"),
                        "enabled": False, "schedule": {"type": "weekdays", "time": "17:30"}}
            tasks = Mock()
            tasks.tasks.return_value = [existing]
            imports = {"mail_app.store": SimpleNamespace(Store=Mock()),
                       "mail_app.work": SimpleNamespace(WorkTasks=Mock(return_value=tasks))}
            with patch("index_futures_basis.recent_brief.work_automation.importlib.import_module", side_effect=imports.__getitem__):
                result = register_task(root, project)
            self.assertFalse(result["created"])
            self.assertFalse(result["enabled"])
            self.assertEqual(result["schedule"]["time"], "17:30")
            tasks.save.assert_not_called()
            tasks.start.assert_not_called()


class BriefFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_generate_button_opens_result_after_background_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            service = BasisService(Path(directory), "demo")
            window = Window(service, auto_start=False)
            response = {"folder": directory, "pdf": str(Path(directory)/PDF_NAME),
                        "word": str(Path(directory)/WORD_NAME), "refresh": {"requested": False}}
            try:
                with patch("index_futures_basis.recent_brief.workflow.generate_for_service", return_value=response) as generate, \
                     patch("index_futures_basis.desktop.QDesktopServices.openUrl", return_value=True) as open_url:
                    window.brief_generate.click()
                    deadline = time.monotonic()+10
                    while window.worker is not None and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.01)
                    self.assertIsNone(window.worker)
                    generate.assert_called_once()
                    self.assertEqual(open_url.call_count, 1)
                    self.assertTrue(open_url.call_args.args[0].toLocalFile().endswith(PDF_NAME))
                    self.assertTrue(window.brief_generate.isEnabled())
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_frontend_error_does_not_open_previous_pdf_as_new(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Window(BasisService(Path(directory), "demo"), auto_start=False)
            try:
                with patch("index_futures_basis.recent_brief.workflow.generate_for_service", side_effect=ValueError("missing input")), \
                     patch("index_futures_basis.desktop.QDesktopServices.openUrl") as open_url:
                    window.brief_generate.click()
                    deadline = time.monotonic()+10
                    while window.worker is not None and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.01)
                    self.assertIn("missing input", window.progress_label.text())
                    open_url.assert_not_called()
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
