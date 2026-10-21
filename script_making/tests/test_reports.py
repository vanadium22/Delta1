"""Offline regression tests using synthetic workbooks and temporary folders."""
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED
from http.server import ThreadingHTTPServer

from script_making.app import Application, handler_for
from script_making.query import (build_predicate, data_bounds, fuzzy_match, normalized,
                                 number, parse_epsilon, query_table, read_table)
from script_making.storage import (ReportError, Settings, catalog, filename, identify,
                                   save_files, sha256, sync_reports)


def fixture(path, sheet="存续合约估值", headers=None, rows=None, inflated=False):
    """Minimal OOXML fixture; no real report data or workbook authoring library."""
    headers = headers or ["交易确认书编号", "交易对手名称", "金额"]
    rows = rows if rows is not None else [["SYNTHETIC-1", "示例证券投资总部", 1e-10],
                                        ["SYNTHETIC-2", "示例客户", 10]]
    def col(i):
        result = ""
        while i:
            i, remainder = divmod(i - 1, 26)
            result = chr(65 + remainder) + result
        return result
    content = []
    offset = 2 if sheet == "存续合约估值" else 1
    for row_index, values in enumerate([headers] + rows, offset):
        cells = []
        for index, value in enumerate(values, 1):
            ref = col(index) + str(row_index)
            if value is None:
                continue
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        content.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    if inflated:
        content.append('<row r="1048576"><c r="BH1048576" s="0"/></row>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:BH1048576"/><sheetData>' + "".join(content) + "</sheetData></worksheet>")
    return path


class FilteringTests(unittest.TestCase):
    def test_abbreviations_and_contiguous_words(self):
        for term in ("申万", "证投", "证券投资", "申万/证投", "不存在 / 证投", "申万 证投"):
            with self.subTest(term=term):
                self.assertTrue(fuzzy_match("申万宏源证券投资总部", term))
        self.assertFalse(fuzzy_match("申万宏源证券投资总部", "投证"))
        self.assertFalse(fuzzy_match("申万宏源证券投资总部", "申万 不存在"))

    def test_unicode_and_zero_search(self):
        self.assertTrue(fuzzy_match("ＡＢＣ", "abc"))
        self.assertTrue(fuzzy_match(0, "0"))
        self.assertEqual(normalized(0), "0")

    def test_numbers_percent_missing_and_infinite(self):
        self.assertEqual(number("1,234.5"), 1234.5)
        self.assertEqual(number("５％"), .05)
        self.assertEqual(number("1e-8"), 1e-8)
        for value in (None, "", " ", "n/a", "NaN", "inf", True):
            self.assertIsNone(number(value))

    def predicate(self, op, **kwargs):
        return build_predicate({"type": "number"}, {"op": op, **kwargs}, 1e-8)

    def test_zero_eps_and_missing(self):
        zero, nonzero = self.predicate("zero"), self.predicate("nonzero")
        for value in (0, -0.0, 1e-10, -1e-10, 1e-8, -1e-8):
            self.assertTrue(zero(value)); self.assertFalse(nonzero(value))
        for value in (-1e-7, 1e-7):
            self.assertFalse(zero(value)); self.assertTrue(nonzero(value))
        for value in ("", None, "NaN"):
            self.assertFalse(zero(value)); self.assertFalse(nonzero(value))

    def test_tolerant_range_and_strict_comparison(self):
        between = self.predicate("range", min="0", max="1")
        for value in (-5e-9, 0, .5, 1 + 5e-9):
            self.assertTrue(between(value))
        for value in (-1e-6, 1 + 1e-6, None):
            self.assertFalse(between(value))
        self.assertFalse(self.predicate("gt", value="0")(5e-9))
        self.assertTrue(self.predicate("gt", value="0")(1e-7))
        self.assertTrue(self.predicate("gte", value="0")(-5e-9))
        self.assertTrue(self.predicate("lt", value="0")(-1e-7))
        self.assertFalse(self.predicate("ne", value="0")(5e-9))

    def test_open_range_percent_and_invalid_input(self):
        self.assertTrue(self.predicate("range", min="5%")(.06))
        self.assertTrue(self.predicate("range", max="5%")(-5))
        for condition in ({"op": "range", "min": "10", "max": "1"},
                          {"op": "range", "min": "bad"}, {"op": "eq", "value": "nan"}):
            with self.assertRaises(ReportError):
                build_predicate({"type": "number"}, condition, 1e-8)
        for epsilon in ("-1", "NaN", "inf", "bad"):
            with self.assertRaises(ReportError):
                parse_epsilon(epsilon)
        self.assertEqual(parse_epsilon("0"), 0)

    def test_dates_and_empty(self):
        check = build_predicate({"type": "date"}, {"op":"range","min":"2026-10-14","max":"2026-10-16"}, 0)
        self.assertTrue(check("2026-10-16 15:00:00"))
        self.assertFalse(check("2026-10-17")); self.assertFalse(check(None))
        with self.assertRaises(ReportError):
            build_predicate({"type": "date"}, {"op":"range","min":"2026-10-17","max":"2026-10-16"}, 0)
        self.assertTrue(build_predicate({"type": "number"}, {"op":"blank"}, 0)(" "))
        self.assertFalse(build_predicate({"type": "number"}, {"op":"blank"}, 0)(0))

    def test_combined_sort_and_pagination(self):
        table = {"columns":[{"id":"c0","type":"text"},{"id":"c1","type":"number"}],
                 "rows":[["示例证券投资", 0],["示例证券投资", 3],["其他", 10],["示例证券投资", None]],
                 "source_rows":[2,3,4,5]}
        result = query_table(table, {"filters":[{"column":"c0","op":"fuzzy","value":"证投"},
                                                {"column":"c1","op":"nonzero"}]})
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["rows"][0]["excel_row"], 3)
        result = query_table(table, {"sort":{"column":"c1","direction":"desc"}, "page_size":2, "page":2})
        self.assertEqual([r["values"][1] for r in result["rows"]], [0,None])
        self.assertEqual(query_table(table, {"search":"不存在"})["matched"], 0)
        with self.assertRaises(ReportError):
            query_table(table, {"filters":[{"column":"wrong"}]})


class FileTests(unittest.TestCase):
    def setUp(self):
        self.test_cache = (Path(__file__).resolve().parents[1] / "cache" / "test-temp")
        self.test_cache.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=self.test_cache)
        self.root = Path(self.tmp.name)

    def tearDown(self):
        assert self.root.resolve().is_relative_to(self.test_cache.resolve())
        self.tmp.cleanup()

    def pair(self, root, day):
        return {kind: fixture(root / day / filename(kind, day), sheet=sheet)
                for kind, sheet in [("swap","存续合约估值"), ("review","簿记要素")]}

    def test_skip_format_only_millionth_row_and_types(self):
        path = fixture(self.root / "bounds.xlsx", inflated=True)
        self.assertEqual(data_bounds(path, "存续合约估值"), (4,3))
        table = read_table(path, "存续合约估值")
        self.assertEqual(len(table["rows"]), 2)
        self.assertEqual(table["columns"][2]["type"], "number")
        self.assertEqual(table["source_rows"], [3,4])

    def test_identifiers_remain_text_and_percent_column_is_numeric(self):
        path = fixture(self.root / "typed.xlsx", headers=["标的代码","盈亏/名本","数字"], rows=[["000001","5%",0],["000002","-0.00%",2]])
        table = read_table(path,"存续合约估值")
        self.assertEqual([c["type"] for c in table["columns"]], ["text","number","number"])
        self.assertTrue(table["columns"][1]["percent"])
        self.assertEqual(table["rows"][0][0], "000001")

    def test_pair_copy_hash_idempotence_and_catalog(self):
        sources = self.pair(self.root/"source", "2026-10-14")
        settings = Settings(self.root/"app")
        result = save_files(settings.data_path(), sources, "2026-10-14", "本地已有材料")
        again = save_files(settings.data_path(), sources, "2026-10-14", "共享目录下载")
        self.assertEqual(again["files"]["swap"]["origin"], "共享目录下载")
        self.assertEqual(again["files"]["swap"]["original_origin"], "本地已有材料")
        for kind, source in sources.items():
            saved = Path(result["files"][kind]["path"])
            self.assertTrue(saved.is_file())
            self.assertEqual(sha256(source), sha256(saved))
        self.assertTrue(catalog(settings)["dates"][0]["complete"])

    def test_download_latest_before_today_across_weekend(self):
        source = self.root/"source"
        self.pair(source, "2026-10-15"); self.pair(source, "2026-10-16"); self.pair(source, "2026-10-19")
        result = sync_reports({"source_root":str(source)}, self.root/"data", date(2026,10,19))
        self.assertEqual(result["date"],"2026-10-16")
        self.assertEqual(len(result["files"]),2)

    def test_auto_sync_downloads_missing_then_reuses_verified_pair(self):
        source, destination = self.root / "source", self.root / "saved"
        self.pair(source, "2026-09-30")
        values = {"source_root": str(source)}
        # The upstream date folders cover exchange holidays, not a weekday guess.
        result = sync_reports(values, destination, date(2026, 10, 8), only_missing=True)
        self.assertEqual(result["date"], "2026-09-30")
        with patch("script_making.storage.shutil.copyfile", side_effect=AssertionError("unexpected copy")):
            result = sync_reports(values, destination, date(2026, 10, 8), only_missing=True)
        self.assertTrue(result["reused"])
        (destination / result["date"] / filename("review", result["date"])).unlink()
        result = sync_reports(values, destination, date(2026, 10, 8), only_missing=True)
        self.assertTrue((destination / result["date"] / filename("review", result["date"])).is_file())
        self.pair(source, "2026-10-08")
        result = sync_reports(values, destination, date(2026, 10, 9), only_missing=True)
        self.assertEqual(result["date"], "2026-10-08")

    def test_auto_sync_does_not_trust_changed_local_file(self):
        source, destination = self.root / "source", self.root / "saved"
        self.pair(source, "2026-10-16")
        values = {"source_root": str(source)}
        sync_reports(values, destination, date(2026, 10, 19), only_missing=True)
        (destination / "2026-10-16" / filename("review", "2026-10-16")).write_text("corrupted")
        result = sync_reports(values, destination, date(2026, 10, 19), only_missing=True)
        self.assertEqual(result["updated"], ["review"])
        self.assertEqual(sha256(destination / "2026-10-16" / filename("review", "2026-10-16")),
                         sha256(source / "2026-10-16" / filename("review", "2026-10-16")))
        self.assertEqual(next((destination / "_revisions").rglob("*.xlsx")).read_text(), "corrupted")

    def test_missing_latest_pair_never_silently_falls_back(self):
        source = self.root/"source"
        self.pair(source,"2026-10-14")
        fixture(source/"2026-10-15"/filename("swap","2026-10-15"))
        with self.assertRaisesRegex(ReportError,"未回退"):
            sync_reports({"source_root":str(source)}, self.root/"data", date(2026,10,16))
        self.assertFalse((self.root/"data"/"2026-10-14").exists())

    def test_invalid_second_file_publishes_neither(self):
        sources=self.pair(self.root/"source","2026-10-14")
        sources["review"].write_text("broken",encoding="utf-8")
        with self.assertRaises(ReportError):
            save_files(self.root/"data",sources,"2026-10-14","测试")
        self.assertFalse((self.root/"data"/"2026-10-14").exists())

    def test_different_existing_file_is_preserved(self):
        sources=self.pair(self.root/"source","2026-10-14")
        result=save_files(self.root/"data",sources,"2026-10-14","测试")
        digest=sha256(Path(result["files"]["swap"]["path"]))
        fixture(sources["swap"],rows=[["CHANGED","示例",999]])
        with self.assertRaisesRegex(ReportError,"保留原文件"):
            save_files(self.root/"data",sources,"2026-10-14","测试")
        self.assertEqual(sha256(Path(result["files"]["swap"]["path"])),digest)

    def test_configuration_reload_and_path_safety(self):
        settings=Settings(self.root/"app")
        values=settings.update({"source_root":str(self.root/"source"),"data_dir":"data/changed","epsilon":"1e-6"})
        self.assertEqual(Settings(self.root/"app").get(), values)
        self.assertEqual(settings.data_path(),(self.root/"app/data/changed").resolve())
        for name in ("../收益互换日报(2026-10-14)-D1.xlsx","收益互换日报(2026-02-30)-D1.xlsx"):
            with self.assertRaises(ReportError):
                identify(name)

    def test_async_sync_uses_updated_path_and_saves_pair(self):
        source = self.root / "configured-source"
        self.pair(source, "2000-01-07")
        application = Application(self.root / "app")
        application.settings.update({"source_root": str(source)})
        application.start_sync()
        deadline = time.monotonic() + 15
        while application.job["state"] == "running" and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertEqual(application.job["state"], "success", application.job)
        self.assertEqual(application.job["result"]["date"], "2000-01-07")
        self.assertTrue(catalog(application.settings)["dates"][0]["complete"])
        application.start_sync(only_missing=True)
        deadline = time.monotonic() + 15
        while application.job["state"] == "running" and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertEqual(application.job["state"], "success", application.job)
        self.assertTrue(application.job["result"]["reused"])

    def test_loopback_api_settings_query_and_foreign_origin(self):
        application=Application(self.root/"app")
        save_files(application.settings.data_path(),self.pair(self.root/"source","2026-10-14"),"2026-10-14","测试")
        server=ThreadingHTTPServer(("127.0.0.1",0),handler_for(application))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base="http://127.0.0.1:"+str(server.server_port)
        try:
            with urlopen(base+"/api/catalog",timeout=5) as response:
                self.assertEqual(json.load(response)["dates"][0]["date"],"2026-10-14")
            with urlopen(base+"/api/settings",timeout=5) as response:
                self.assertEqual(json.load(response)["settings"]["data_dir"], "@shared")
            body=json.dumps({"kind":"swap","date":"2026-10-14","filters":[{"column":"c1","op":"fuzzy","value":"证投"}]}).encode()
            with urlopen(Request(base+"/api/query",data=body,headers={"Content-Type":"application/json"}),timeout=5) as response:
                self.assertEqual(json.load(response)["matched"],1)
            request=Request(base+"/api/settings",data=b'{"data_dir":"data/changed"}',headers={"Content-Type":"application/json"})
            with urlopen(request,timeout=5) as response:
                self.assertEqual(json.load(response)["settings"]["data_dir"],"data/changed")
            with self.assertRaises(HTTPError) as context:
                urlopen(Request(base+"/api/settings",data=b"{}",headers={"Content-Type":"application/json","Origin":"https://example.invalid"}),timeout=5)
            self.assertEqual(context.exception.code,403)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
