"""Synthetic Excel and native UI checks. No company sources or email sending."""
import json
import os
import tempfile
import time
import unittest
from datetime import date
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from script_making.desktop import Window
from script_making.download_widgets import DownloadsDialog
from script_making.downloads import archive_path
from script_making.query import read_table
from script_making.service import ALL_REPORTS, ReportService
from script_making.statistics import (DEFAULT_CONFIG, FIELDS, GROUPS, build_snapshot, classify,
                                      load_config, pnl_statistics, risk_statistics, save_config,
                                      validated_config)
from script_making.statistics_export import export_bundle, render_pages, save_image, mail_content
from script_making.statistics_widgets import StatisticsPage
from script_making.storage import ReportError, filename, sha256
from script_making.tests.test_reports import fixture


def workbook(path, sheets):
    """Small raw OOXML fixture; values only, no business source content."""
    fixture(path)
    with ZipFile(path) as source:
        base = {name: source.read(name) for name in ("[Content_Types].xml", "_rels/.rels")}
    rels, entries = [], []
    with ZipFile(path, "w", ZIP_DEFLATED) as target:
        for key, value in base.items():
            target.writestr(key, value)
        for index, (name, rows) in enumerate(sheets.items(), 1):
            entries.append(f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>')
            rels.append(f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>')
            xml = []
            for line, row in enumerate(rows, 1):
                cells = []
                for pos, value in enumerate(row, 1):
                    if value is None:
                        continue
                    number, letters = pos, ""
                    while number:
                        number, remainder = divmod(number - 1, 26)
                        letters = chr(65 + remainder) + letters
                    ref = letters + str(line)
                    if isinstance(value, (int, float)):
                        cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
                xml.append(f'<row r="{line}">{"".join(cells)}</row>')
            target.writestr(f"xl/worksheets/sheet{index}.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(xml) + "</sheetData></worksheet>")
        target.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + "".join(entries) + "</sheets></workbook>")
        target.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>")
    return path


def pnl_book(path, day, value=1234.56):
    return workbook(path, {"累积盈亏统计": [[], [], [None, day], [],
                                           [None, "净利润", "交易台", "当日收入"],
                                           [None, value, "境内权益互换台", 999999],
                                           [None, "注:境内权益互换台取T-2日数据"]],
                           "每日盈亏统计": [[], ["日期", "境内权益互换台", "境内权益互换台"],
                                          [day, 100, 200]]})


def risk_book(path, day, rows=None, reorder=False):
    rows = rows if rows is not None else [["000300.SH", "示例指数", 100, 10, -2, -500000],
                                          ["IF2612.CFE", "示例股指", 300, -5, 4, 600000],
                                          ["600001.SH", "示例股票", 200, 20, 8, 800000],
                                          ["159001.SZ", "示例货币", 9000, 900, 9, 9000000],
                                          ["511660.OF", "示例货币别名", 8000, 800, 8, 8000000],
                                          ["512100.SH", "示例ETF", 400, 40, 5, 499999]]
    headers = list(FIELDS)
    if reorder:
        order = [5, 1, 4, 3, 0, 2]
        headers = [headers[i] for i in order]
        rows = [[row[i] for i in order] for row in rows]
    return workbook(path, {"总表": [["合成标题"], [], [], [], [None] * 9 + [day]],
                           "风险盈亏统计": [[]] * 5 + [headers] + rows,
                           "存续合约估值": [[], ["编号", "数值", "名称"], ["TEST", 1, "样例"]]})


class StatisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = ReportService(self.root / "module")
        self.service.update_settings({"data_dir": str(self.root / "data")})
        self.config = validated_config(DEFAULT_CONFIG)
        self.pnl_path = archive_path(self.service.settings, "pnl") / "2026-10-19" / "盈亏统计_2026-10-19_new_adjust.xlsx"
        self.previous_path = archive_path(self.service.settings, "pnl") / "2026-10-16" / "盈亏统计_2026-10-16_new_adjust.xlsx"
        pnl_book(self.pnl_path, "2026-10-19")
        pnl_book(self.previous_path, "2026-10-16", 1000)
        self.swap_path = self.service.settings.data_path() / "2026-10-14" / filename("swap", "2026-10-14")
        risk_book(self.swap_path, "2026-10-14")
        self.strategy_path = archive_path(self.service.settings, "strategy") / "2026-10-19" / "D1策略台日报_2026-10-19.xlsx"
        risk_book(self.strategy_path, "2026-10-19", reorder=True)
        self.selections = {"pnl": "2026-10-19", "previous": "2026-10-16", "swap": "2026-10-14", "strategy": "2026-10-19"}

    def tearDown(self):
        self.app.processEvents()
        self.temp.cleanup()

    def snapshot(self):
        return build_snapshot(self.service, self.selections, self.config)

    def test_pnl_label_lookup_difference_notes_and_original_grid(self):
        hashes = [sha256(self.pnl_path), sha256(self.previous_path)]
        result = pnl_statistics(self.pnl_path, "2026-10-19", (self.previous_path, "2026-10-16"))
        self.assertEqual(Decimal(result["current"]), Decimal("1234.56"))
        self.assertEqual(Decimal(result["change"]), Decimal("234.56"))
        self.assertEqual(result["row"], 6)
        self.assertIn("T-2", result["notes"][0])
        self.assertIn(3, result["grid"]["source_rows"])
        self.assertIn(7, result["grid"]["source_rows"])
        self.assertEqual(hashes, [sha256(self.pnl_path), sha256(self.previous_path)])

    def test_missing_previous_not_zero_and_cross_year_no_subtraction(self):
        result = pnl_statistics(self.pnl_path, "2026-10-19")
        self.assertIsNone(result["change"])
        self.assertIsNone(result["previous"])
        old = pnl_book(self.root / "prior.xlsx", "2025-12-31", 9999)
        result = pnl_statistics(self.pnl_path, "2026-10-19", (old, "2025-12-31"))
        self.assertIsNone(result["change"])
        self.assertIn("跨年", result["warning"])
        with self.assertRaisesRegex(ReportError, "早于"):
            pnl_statistics(self.pnl_path, "2026-10-19", (self.pnl_path, "2026-10-19"))

    def test_missing_cached_profit_and_date_mismatch_rejected(self):
        empty = pnl_book(self.root / "empty.xlsx", "2026-10-19", None)
        with self.assertRaisesRegex(ReportError, "未按零"):
            pnl_statistics(empty, "2026-10-19")
        with self.assertRaisesRegex(ReportError, "日期"):
            pnl_statistics(self.pnl_path, "2026-10-20")

    def test_risk_boundary_negative_exclusion_and_column_reorder(self):
        for kind, path in (("swap", self.swap_path), ("strategy", self.strategy_path)):
            result = risk_statistics(path, self.selections[kind], kind, self.config)
            self.assertEqual([g["count"] for g in result["groups"]], [2, 1])
            first = result["groups"][0]
            self.assertEqual(Decimal(first["net"]), 100000)
            self.assertEqual(Decimal(first["gross"]), 1100000)
            self.assertEqual(Decimal(first["daily"]), 5)
            self.assertEqual(set(result["excluded"]), {"159001.SZ", "511660.OF"})
            self.assertEqual(len(first["rows"][0]), 6)
        config = validated_config({**self.config, "metric": "当日盈亏", "threshold": "30"})
        changed = risk_statistics(self.swap_path, "2026-10-14", "swap", config)
        self.assertEqual([g["count"] for g in changed["groups"]], [0, 1])
        self.assertEqual(changed["groups"][1]["rows"][0][0], "512100.SH")

    def test_non_equity_futures_and_other_indices_are_not_misclassified(self):
        self.assertEqual(classify("IM2612.CFE"), GROUPS[0])
        self.assertEqual(classify("159845.SZ"), GROUPS[1])
        self.assertIsNone(classify("T2612.CFE"))
        self.assertIsNone(classify("000001.SH"))
        self.assertIsNone(classify("511660.OF"))

    def test_duplicate_unknown_and_missing_metric_block_partial_totals(self):
        base = ["600001.SH", "示例", 100, 10, 1, 600000]
        for name, rows, error in (("duplicate", [base, base], "重复"),
                                   ("unknown", [["T2612.CFE", *base[1:]]], "无法归入"),
                                   ("missing", [[*base[:5], None]], "未按零")):
            with self.subTest(name=name):
                path = risk_book(self.root / f"{name}.xlsx", "2026-10-14", rows)
                with self.assertRaisesRegex(ReportError, error):
                    risk_statistics(path, "2026-10-14", "swap", self.config)

    def test_settings_roundtrip_and_invalid_threshold(self):
        values = save_config(self.service.settings.root, {**self.config, "exclusions": "159001.sz\n511660.OF",
                                                         "to": "test@example.com", "threshold": "600000"})
        self.assertEqual(load_config(self.service.settings.root), values)
        self.assertEqual(values["exclusions"], ["159001.SZ", "511660.OF"])
        for threshold in ("-1", "NaN", "Infinity", "bad"):
            with self.assertRaises(ReportError):
                validated_config({"threshold": threshold})

    def test_snapshot_independent_dates_persist_and_changed_file_rejected(self):
        snap = self.snapshot()
        self.assertEqual(snap["errors"], {})
        self.assertNotEqual(snap["risks"]["swap"]["date"], snap["risks"]["strategy"]["date"])
        path = self.service.settings.data_path() / "statistics" / "records" / (snap["id"] + ".json")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), snap)
        real = sha256
        calls = {}
        def changed(path):
            key = str(path)
            calls[key] = calls.get(key, 0) + 1
            return "changed" if calls[key] > 1 else real(path)
        with patch("script_making.statistics.sha256", side_effect=changed):
            with self.assertRaisesRegex(ReportError, "发生变化"):
                self.snapshot()

    def test_one_source_error_keeps_other_independent_result_visible(self):
        self.strategy_path.write_bytes(b"corrupt")
        snap = self.snapshot()
        self.assertIn("strategy", snap["errors"])
        self.assertIn("swap", snap["risks"])
        self.assertIsNotNone(snap["pnl"])
        self.assertIn("未生成", render_pages(snap)[1])

    def test_full_image_and_mail_same_snapshot_two_attachments(self):
        snap = self.snapshot()
        pages = render_pages(snap)
        values = {**self.config, "to": "test@example.com", "cc": "copy@example.com"}
        folder = export_bundle(self.root / "exports", snap, pages, values)
        message = BytesParser(policy=policy.default).parsebytes((folder / "邮件草稿.eml").read_bytes())
        self.assertEqual(message["To"], "test@example.com")
        self.assertEqual({part.get_filename() for part in message.iter_attachments()}, {"pnl1.png", "risk.png"})
        self.assertEqual(message.get_content_type(), 'multipart/related')
        self.assertEqual(message['MIME-Version'], '1.0')
        html = message.get_body(preferencelist=('html',)).get_content()
        self.assertIn('src="cid:pnl1@daily-report"', html)
        self.assertIn('src="cid:risk@daily-report"', html)
        self.assertIn('&nbsp;&nbsp;时祺', html)
        self.assertEqual(len([p for p in message.walk() if p.get_content_maintype() == 'image']), 2)
        self.assertIn('data:image/png;base64,', pages[0])
        self.assertNotIn('data:image/png;base64,', pages[1])
        body = message.get_body(preferencelist=("plain",)).get_content()
        for expected in ("尊敬的领导、同事", "顺颂\r\n  时祺", "234.56", "2026-10-14", "2026-10-19", "T-2"):
            self.assertIn(expected, body)
        self.assertNotIn("{{", body)
        for attachment in message.iter_attachments():
            self.assertEqual(attachment.get_content_disposition(), 'inline')
            self.assertEqual(attachment.get_payload(decode=True), (folder / attachment.get_filename()).read_bytes())
        long = pages[1].replace("</body>", "<p>末尾行</p>" * 60 + "</body>")
        _, height = save_image(long, self.root / "long.png")
        self.assertGreater(height, 1000)
        self.assertEqual(QImage(str(self.root / "long.png")).height(), height)
        other = export_bundle(self.root / "exports", snap, pages, values)
        self.assertNotEqual(other, folder)

    def test_mail_header_injection_and_invalid_addresses_rejected(self):
        snap = self.snapshot()
        for values in ({"subject": "bad\nBcc: victim@example.com"}, {"to": "invalid"}):
            with self.assertRaises(ReportError):
                export_bundle(self.root / "exports", snap, render_pages(snap), values)

    def wait_dialog(self, dialog):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.app.processEvents()
            if dialog.worker is None and dialog.snapshot is not None:
                return
            time.sleep(.01)
        self.fail(dialog.error.text() or "统计未完成")

    def test_statistics_ui_invalidates_stale_export_and_waits_on_close(self):
        window = Window(self.service, auto_start=False)
        window.show()
        window.open_statistics()
        dialog = window.statistics_page
        self.assertIs(window.content.currentWidget(), dialog)
        self.assertFalse(dialog.isWindow())
        self.wait_dialog(dialog)
        self.assertEqual(dialog.tabs.count(), 2)
        self.assertFalse(hasattr(dialog, "chart_views"))
        self.assertEqual(dialog.previous.currentData(), "2026-10-16")
        self.assertTrue(dialog.export_button.isEnabled())
        dialog.threshold.setText("900000")
        self.assertIsNone(dialog.snapshot)
        self.assertFalse(dialog.export_button.isEnabled())
        dialog.generate()
        self.wait_dialog(dialog)
        self.assertEqual(dialog.snapshot["config"]["threshold"], "900000")
        self.assertEqual(load_config(self.service.settings.root)["threshold"], "900000")
        from script_making.daily_job import run_once
        code, result = run_once(self.service.settings.root, date(2026, 10, 21), local_only=True)
        self.assertEqual(code, 0, result)
        cli = json.loads(Path(result["statistics_record"]).read_text(encoding="utf-8"))
        self.assertEqual(cli["config"]["threshold"], "900000")
        self.assertEqual(cli["risks"], dialog.snapshot["risks"])
        original = build_snapshot
        def slow(*args):
            time.sleep(.1)
            return original(*args)
        with patch("script_making.statistics_widgets.build_snapshot", side_effect=slow):
            dialog.generate()
            window.close()
            self.assertTrue(window.isVisible())
            deadline = time.monotonic() + 10
            while dialog.worker and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
        self.app.processEvents()
        self.assertFalse(window.isVisible())

    def test_signed_equity_etf_filter_and_cross_date_totals(self):
        rows = [["600001.SH", "合成股票300", 100, -10, -2, -600000],
                ["512100.SH", "合成中证1000ETF", 200, 20, -3, -500000],
                ["159919.SZ", "合成沪深300ETF", -50, -5, 4, 700000],
                ["512200.SH", "合成其他ETF", 30, 3, -4, -800000],
                ["600002.SH", "合成边界内", 999, 999, 1, -499999],
                ["159001.SZ", "中证500货币基金", 999, 999, 1, 9000000]]
        risk_book(self.swap_path, self.selections["swap"], rows)
        snap = self.snapshot()
        index, equity = snap["risks"]["swap"]["groups"]
        self.assertEqual((index["count"], index["net"]), (2, "200000"))
        self.assertEqual((equity["count"], equity["net"]), (2, "-1400000"))
        self.assertEqual(snap["risk_totals"][0]["total"], "550")
        self.assertEqual(snap["risk_totals"][0]["net"], "300000")
        self.assertEqual(snap["risk_totals"][1]["net"], "-600000")
        self.assertEqual(snap["risk_totals"][1]["count"], 3)
        self.assertEqual(snap["risk_totals"][0]["dates"], {"swap": "2026-10-14", "strategy": "2026-10-19"})
        html = render_pages(snap)[1]
        self.assertEqual(html.count("两日报总汇总"), 2)
        self.assertNotIn("Σ|x|", html)
        self.assertIn("-600,000.00", html)
        self.strategy_path.write_bytes(b"bad")
        partial = self.snapshot()
        self.assertEqual(partial["risk_totals"], [])
        self.assertNotIn("两日报总汇总", render_pages(partial)[1])

    def test_index_etf_names_and_no_stock_or_number_substring_false_match(self):
        for name in ("1000ETF", "中证500", "沪深300ETF", "中证50ETF", "科创50", "创业板ETF", "中证Ａ５００"):
            self.assertEqual(classify("512100.SH", name), GROUPS[0], name)
        for name in ("合成其他ETF", "合成3000ETF", "合成1500ETF"):
            self.assertEqual(classify("512100.SH", name), GROUPS[1], name)
        self.assertEqual(classify("600001.SH", "中证300合成股票"), GROUPS[1])
        self.assertIsNone(classify("T2612.CFE", "中证500"))

    def test_five_pnl_rows_highlight_and_default_mail_migration(self):
        workbook(self.pnl_path, {"累积盈亏统计": [[], [], [None, "2026-10-19"], [],
                    [None, "净利润", "交易台"], [None, 1234.56, "境内权益互换台"],
                    [None, 10, "明细一"], [None, 20, "明细二"],
                    [None, 30, "明细三"], [None, 40, "明细四"], [None, 50, "其他台"]]})
        snap = self.snapshot()
        html = render_pages(snap)[0]
        self.assertIn('size="4"><b>境内权益互换台</b>', html)
        self.assertEqual(html.count('bgcolor="#185b59"'), 4)
        self.assertEqual(html.count('bgcolor="#fff0bf"'), 16)
        from script_making.statistics import LEGACY_DEFAULT_TEMPLATES, DEFAULT_TEMPLATE
        for old in LEGACY_DEFAULT_TEMPLATES:
            self.assertEqual(validated_config({**self.config, "template": old})["template"], DEFAULT_TEMPLATE)
            body = mail_content(snap, {**self.config, "template": old})[1]
            self.assertTrue(body.endswith("顺颂\n  时祺"))
            self.assertNotIn("30份", body)
            self.assertLess(len(body), 650)
        custom = "我的开头\n{{dates}}\n自定义结尾"
        self.assertEqual(validated_config({**self.config, "template": custom})["template"], custom)
        from script_making.statistics_export import mail_html
        self.assertIn('&lt;script&gt;', mail_html('<script> & 合成正文'))
        self.assertNotIn('<script>', mail_html('<script> & 合成正文'))

    def test_unified_queries_duplicate_headers_total_grid_and_four_download_tabs(self):
        data = self.service.query_catalog()
        self.assertEqual(set(data["reports"]), set(ALL_REPORTS))
        self.assertEqual(self.service.sheets("pnl", "2026-10-19"), ["累积盈亏统计", "每日盈亏统计"])
        table = read_table(self.pnl_path, "每日盈亏统计")
        self.assertEqual(table["columns"][1]["name"], table["columns"][2]["name"])
        self.assertNotEqual(table["columns"][1]["id"], table["columns"][2]["id"])
        result = self.service.query({"kind": "strategy", "date": "2026-10-19", "sheet": "总表"})
        self.assertEqual(result["layout"], "grid")
        self.assertEqual(result["rows"][0]["excel_row"], 1)
        dialog = DownloadsDialog(self.service, lambda key: None)
        self.assertEqual(set(dialog.panels), set(ALL_REPORTS))
        self.assertEqual(dialog.panels["swap"]["files"].count(), 1)
        dialog.reject()
        window = Window(self.service, auto_start=False)
        window.show()
        window.refresh_catalog()
        deadline = time.monotonic() + 10
        while (window.worker or not window.catalog_data) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        window.switch_kind("pnl")
        while window.worker and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNotNone(window.result)
        self.assertEqual(window.result["sheet"], "累积盈亏统计")
        self.assertNotIn("未齐", window.date_combo.currentText())
        with patch.object(window, "start_sync") as sync:
            window.start_download("swap")
            sync.assert_called_once()
        window.close()


if __name__ == "__main__":
    unittest.main()
