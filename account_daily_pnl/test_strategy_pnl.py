import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from script_making.storage import ReportError
from shared_data.paths import DataPaths

from .strategy_pnl import DESK, FIELDS, GROUPS, latest_report, summarize


def make_report(folder, day, rows):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"D1策略台日报_{day}.xlsx"
    book = Workbook()
    book.active.title = "总表"
    book.active["J5"] = date.fromisoformat(day)
    sheet = book.create_sheet("合约信息")
    sheet.append(["合约估值", None])
    sheet.append([*FIELDS, "合约编号"])
    for row in rows:
        sheet.append([*row, "test-contract"])
    book.save(path)
    book.close()
    return path


class StrategyPnlTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_aggregates_ledger_rows_preserving_start_date_and_etf_subset(self):
        rows = [
            (DESK, "2026-01-05", "IF2612.CFE", "沪深300股指期货", "CNY", 7, -2, -6, 1),
            (DESK, "2026-01-05", "159629.SZ", "１０００ETF", "CNY", 8, 1, 2, 3),
            (DESK, "2026-01-05", "159629.SZ", "1000ETF", "CNY", -3, 0, 0, 0),
            (DESK, "2026-01-06", "510050.SH", "上证50ETF", "CNY", -1, 0, -2, 0),
            (DESK, "2026-01-06", "159593.SZ", "中证A50ETF", "CNY", -4, 0, 10, 0),
            (DESK, "2026-01-06", "600000.SH", "样本个股", "CNY", 12, 0, 1, 0),
            (DESK, "2026-01-06", "T2612.CFE", "国债期货", "CNY", 100, 0, 0, 0),
            ("其他交易对手", "2026-01-06", "600000.SH", "样本个股", "CNY", 100, 0, 0, 0),
        ]
        result = summarize(make_report(self.root, "2026-11-19", rows))
        self.assertEqual(result["desk_rows"], 7)
        self.assertEqual([value["rows"] for value in result["totals"].values()], [1, 4, 1, 3])
        self.assertEqual([Decimal(value["realized"]) for value in result["totals"].values()], [5, 1, 12, 5])
        self.assertEqual([Decimal(value["unrealized"]) for value in result["totals"].values()], [-5, 13, 1, 3])
        self.assertEqual(result["by_start_date"]["2026-01-05"][GROUPS[3]]["rows"], 2)
        self.assertEqual(result["index_etfs"]["上证50"]["rows"], 1)
        self.assertEqual(result["unclassified"][0]["code"], "T2612.CFE")

    def test_blank_required_amount_is_reported(self):
        path = make_report(self.root, "2026-11-19", [
            (DESK, "2026-01-05", "159629.SZ", "1000ETF", "CNY", 1, None, 2, 3),
        ])
        with self.assertRaisesRegex(ReportError, "第 3 行.*已实现利率收益"):
            summarize(path)

    def test_local_and_company_sync_require_the_latest_trading_day(self):
        paths = DataPaths.for_repo(self.root)
        as_of = date(2026, 11, 20)
        share = self.root / "for_jrcx"
        source = share / "OTC-Quant" / "pybct" / "LH" / "D1策略台日报" / "report"
        make_report(source, "2026-11-18", [])
        with patch.dict(os.environ, {"SCRIPT_MAKING_SOURCE": str(share), "SCRIPT_MAKING_DATA": str(paths.reports)}):
            for directory in (source, None):
                with self.assertRaisesRegex(ReportError, "应为 2026-11-19.*2026-11-18"):
                    latest_report(paths, as_of, directory)
            current = make_report(source, "2026-11-19", [])
            self.assertEqual(latest_report(paths, as_of, source), (current, "local_directory"))
            archived, mode = latest_report(paths, as_of)
            self.assertEqual(mode, "company_sync")
            self.assertEqual(archived.read_bytes(), current.read_bytes())
            self.assertEqual(latest_report(paths, as_of), (archived, "company_sync"))
