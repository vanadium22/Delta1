import argparse
from collections import Counter
from contextlib import redirect_stdout
from datetime import date, datetime
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openpyxl import load_workbook

from account_daily_pnl import __main__ as app
from account_daily_pnl.baseline import ACCOUNTS, BASE_DAY
from account_daily_pnl.ledger import Ledger, report
from account_daily_pnl.prices import CACHE_COLUMNS, resolve
from account_daily_pnl.seed import INPUTS, install_seed, make_seed
from account_daily_pnl.series import SERIES_FILENAME, load_series
from account_daily_pnl.setup_daily import configure_credentials, register_with_tasks, task_definition
from account_daily_pnl.sources import bct_credential_path, login_values, read_source, write_book, write_source
from shared_data.io import atomic_json, sha256


def record(day, identifier, side, amount, price, *, code="600000.SH", account="2602", flag="OPEN", fee=1):
    balance = amount * price * (200 if code.endswith(".CFE") else 1)
    return {
        "id": identifier, "tradeId": identifier, "tradingDate": day, "dealDate": day, "dealTime": "10:00:00",
        "tradeAccount": ACCOUNTS[account], "instrumentId": code, "direction": side, "openClose": flag,
        "type": "TRADE", "dealAmount": amount, "dealPrice": price, "dealBalance": balance, "fee": fee,
        "dealBalanceWithFee": balance + fee * (1 if side == "BUYER" else -1), "currencyCode": "CNY",
    }


class FakeBct:
    marks = {"2025-12-30": (110, 12), "2025-12-31": (108, 12), "2026-01-05": (111, 9)}
    events = [record("2025-12-30", "buy", "BUYER", 2, 105),
              record("2026-01-05", "sell", "SELLER", 3, 112, flag="CLOSE")]
    downloads = Counter()

    def __init__(self, credentials):
        pass

    def connect(self):
        pass

    def flows(self, days):
        self.downloads.update(("flow", day) for day in days)
        return [item for item in self.events if item["tradingDate"] in days]

    def snapshot(self, day):
        self.downloads["snapshot", day] += 1
        mark, position = self.marks[day]
        return [{"tradingDate": day, "instrumentId": "600000.SH", "instrumentQuote": mark,
                 "currencyCode": "CNY", "netPosition": position}]


class DailyReportTests(unittest.TestCase):
    def setUp(self):
        scratch = os.environ.get("ACCOUNT_PNL_TEST_DIR")
        self.sandbox = TemporaryDirectory(dir=scratch)
        self.addCleanup(self.sandbox.cleanup)
        self.root = Path(self.sandbox.name) / "data"
        self.outputs = Path(self.sandbox.name) / "outputs"
        self.baseline = {"day": BASE_DAY, "positions": [
            {"account": "2602", "code": "600000.SH", "side": "long", "quantity": 10, "price": 100}],
            "equity_candidates": {}, "snapshot": {}}
        atomic_json(self.root / INPUTS[0], self.baseline)
        config = {"accounts": {"2602": {"opening_equity": 1000, "cash_flows_confirmed_through": "2026-01-05"}},
                  "cash_movements": [{"date": "2025-12-31", "account": "2602", "net_deposit": 10}]}
        atomic_json(self.root / "inputs/config.local.json", config)
        self.args = argparse.Namespace(seed=None, import_archive=None, date=None, config=None, bct_script=None,
                                       no_download=False, make_seed=None, prepare=False, only_day=False, no_wind=True,
                                       skip_strategy=True, strategy_source_dir=None)
        mock_swap = patch("account_daily_pnl.swap_report.check_swap",
                          return_value={"date": None, "path": None, "notes": []})
        mock_swap.start()
        self.addCleanup(mock_swap.stop)
        FakeBct.downloads.clear()

    def summary(self, day):
        path = self.outputs / f"场内账户_{day}.xlsx"
        data = load_workbook(path, read_only=True, data_only=True)
        try:
            header, *rows = data["账户统计"].values
            return {r[1]: dict(zip(header, r)) for r in rows}
        finally:
            data.close()

    def test_full_run_generates_strategy_workbook_and_chart_after_account_series(self):
        from account_daily_pnl.strategy_pnl import DESK
        from account_daily_pnl.strategy_reconciliation import BOOK_NAME, CHART_NAME
        from account_daily_pnl.test_strategy_pnl import make_report

        self.args.skip_strategy = False
        self.args.strategy_source_dir = self.root / "strategy-source"
        for stamp, futures in ((BASE_DAY, 40), ("2025-12-30", 15)):
            make_report(self.args.strategy_source_dir, stamp, [
                (DESK, BASE_DAY, "IF2512.CFE", "股指期货", "CNY", futures, 0, 5, 0),
            ])
        with patch("account_daily_pnl.sources.BctClient", FakeBct):
            self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2025, 12, 31)), 0)
        self.assertTrue((self.outputs / SERIES_FILENAME).is_file())
        self.assertGreater((self.outputs / CHART_NAME).stat().st_size, 0)
        book = load_workbook(self.outputs / BOOK_NAME, read_only=True, data_only=True)
        try:
            metrics = {row[0]: row[1:] for row in book["收益汇总"].iter_rows(min_row=2, max_col=3, values_only=True)}
            self.assertEqual(metrics["Excel股指期货"], (-25, -25))
            self.assertEqual(metrics["5526实盘净盈亏"], (0, 0))
            self.assertEqual(metrics["股指差额（5526 − Excel）"], (25, 25))
            self.assertEqual(metrics["替换后合计"], (0, 0))
            self.assertEqual(len(list(book["合约起始日"].values)), 2)
        finally:
            book.close()

        result = self.root / "workbench-result.json"
        args = ["--data", str(self.root), "--output", str(self.outputs), "--scheduled", "--no-wind",
                "--strategy-source-dir", str(self.args.strategy_source_dir), "--wa-output", str(result)]
        days = ["2025-12-30", "2025-12-31"]
        log = StringIO()
        with (patch.object(app, "trading_days", return_value=(days, days[-1])),
              patch("account_daily_pnl.setup_daily.configure_credentials", return_value=FakeBct(None)),
              redirect_stdout(log)):
            self.assertEqual(app.main(args), 0)
        manifest = app.read_json(result)
        self.assertEqual(manifest["mail"]["subject"], "策略台 PnL 汇总 2025-12-30")
        self.assertEqual(len(manifest["mail"]["attachments"]), 2)
        self.assertIn("账户收益截至 2025-12-31，策略台对账截至 2025-12-30", log.getvalue())
        self.assertEqual(load_series(self.outputs / SERIES_FILENAME)["through"], "2025-12-31")
        book = load_workbook(self.outputs / BOOK_NAME, read_only=True, data_only=True)
        try:
            self.assertEqual(book["收益汇总"]["A1"].value, "项目 · 2025-12-30")
            dates = [row[0].date().isoformat() for row in list(book["每日PnL"].values)[1:]]
            self.assertEqual(dates, ["2025-12-30"])
            notes = [row[1] for row in list(book["数据检查"].values)[1:]]
            self.assertTrue(any("账户截止 2025-12-31，对账使用 2025-12-30" in note for note in notes))
        finally:
            book.close()

        (self.args.strategy_source_dir / f"D1策略台日报_{BASE_DAY}.xlsx").unlink()
        with patch("account_daily_pnl.sources.BctClient", FakeBct):
            self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2026, 1, 1)), 0)
        book = load_workbook(self.outputs / BOOK_NAME, read_only=True, data_only=True)
        try:
            metrics = {row[0]: row[1:] for row in book["收益汇总"].iter_rows(min_row=2, max_col=3, values_only=True)}
            self.assertEqual(metrics["Excel股指期货"], (None, None))
            self.assertEqual(metrics["5526实盘净盈亏"], (0, 0))
        finally:
            book.close()

        (self.args.strategy_source_dir / "D1策略台日报_2025-12-30.xlsx").unlink()
        previous = [sha256(self.outputs / name) for name in (BOOK_NAME, CHART_NAME)]
        with patch("account_daily_pnl.sources.BctClient", FakeBct):
            self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2026, 1, 1)), 2)
        self.assertEqual([sha256(self.outputs / name) for name in (BOOK_NAME, CHART_NAME)], previous)

    def test_mail_manifest_freezes_both_attachments_and_deduplicates(self):
        from account_daily_pnl.daily_mail import create_manifest
        from account_daily_pnl.strategy_reconciliation import BOOK_NAME, CHART_NAME

        write_book(self.outputs / BOOK_NAME, [("收益汇总", ("项目 · 2026-11-18", "当日", "年内"),
                                                [("合计", 12, 20)])])
        (self.outputs / CHART_NAME).write_bytes(b"test image bytes")
        first = create_manifest(self.outputs)
        self.assertEqual(first["mail"]["to"], ["meiyifan@swhysc.com"])
        self.assertEqual(len(first["mail"]["attachments"]), 2)
        self.assertEqual(first["mail"]["attachments"][1]["also_attach"], True)
        self.assertEqual(first, create_manifest(self.outputs))
        frozen = Path(first["mail"]["attachments"][0]["path"])
        write_book(self.outputs / BOOK_NAME, [("收益汇总", ("项目 · 2026-11-18", "当日", "年内"),
                                                [("合计", 15, 20)])])
        second = create_manifest(self.outputs)
        self.assertNotEqual(first["delivery_key"], second["delivery_key"])
        self.assertEqual(sha256(frozen), first["mail"]["attachments"][0]["sha256"])

    def test_workbench_output_is_published_only_after_successful_full_run(self):
        from account_daily_pnl.strategy_reconciliation import BOOK_NAME, CHART_NAME

        write_book(self.outputs / BOOK_NAME, [("收益汇总", ("项目 · 2026-11-18", "当日"), [("合计", 12)])])
        (self.outputs / CHART_NAME).write_bytes(b"test image bytes")
        output = self.root / "workbench-result.json"
        args = ["--data", str(self.root), "--output", str(self.outputs), "--scheduled", "--wa-output", str(output)]
        with patch.object(app, "run", return_value=2):
            self.assertEqual(app.main(args), 2)
        self.assertFalse(output.exists())
        with patch.object(app, "run", return_value=0):
            self.assertEqual(app.main(args), 0)
        manifest = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(manifest["mail"]["to"], ["meiyifan@swhysc.com"])

    def test_restart_backfills_skipped_trading_days(self):
        with (patch("account_daily_pnl.sources.BctClient", FakeBct),
              patch("account_daily_pnl.daily_cache.read_source", wraps=read_source) as load_flow):
            app.run(self.args, self.root, self.outputs, datetime(2025, 12, 31))
            app.run(self.args, self.root, self.outputs, datetime(2026, 1, 6))
            digest = sha256(self.outputs / "场内账户_2026-01-05.xlsx")
            app.run(self.args, self.root, self.outputs, datetime(2026, 1, 6))
        days = ["2025-12-30", "2025-12-31", "2026-01-05"]
        self.assertEqual([call.args[2] for call in load_flow.call_args_list], days)
        for day in days:
            self.assertEqual(FakeBct.downloads["flow", day], 1)
            self.assertEqual(FakeBct.downloads["snapshot", day], 1)
        self.assertEqual(len(FakeBct.downloads), 6)
        self.assertEqual(read_source(self.root / "flows/2025-12-31.xlsx", "flow", "2025-12-31"), [])
        self.assertEqual([self.summary(day)["2602"]["单日盈亏"] for day in days], [109, -24, 38])
        self.assertEqual(self.summary(days[-1])["2602"]["总权益"], 1133)
        latest = self.summary(days[-1])["2602"]
        self.assertEqual(latest["基准以来累计净盈亏"], 123)
        self.assertEqual(latest["今年累计净盈亏"], 38)
        self.assertEqual(latest["当日手续费"], 1)
        self.assertEqual(latest["成交估值费前盈亏"], 39)
        self.assertAlmostEqual(latest["今年累计收益率"], 38 / 1095)
        self.assertIsNone(latest["基准以来累计收益率"])
        self.assertIsNone(self.summary(days[-1])["5524"]["总权益"])
        self.assertEqual(sha256(self.outputs / "场内账户_2026-01-05.xlsx"), digest)
        for name in ("历史至今_账户收益.png", "2026年_账户收益.png"):
            self.assertEqual((self.outputs / name).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        series = load_series(self.outputs / SERIES_FILENAME, required_through=days[-1])
        self.assertEqual(len(series["rows"]), 12)
        row = next(item for item in series["rows"] if
                   (item["trading_date"], item["account_id"]) == (days[-1], "2602"))
        self.assertEqual((row["net_pnl"], row["fee"], row["closing_equity"]), ("38.00", "1.00", "1133.00"))
        self.assertIsNone(row["since_baseline_return"])
        self.assertEqual(series["rows"][-1]["account_id"], "total")
        with self.assertRaises(ValueError):
            load_series(self.outputs / SERIES_FILENAME, required_through="2026-01-06")

    def test_historical_flow_edit_replays_only_from_its_trading_day(self):
        with patch("account_daily_pnl.sources.BctClient", FakeBct):
            app.run(self.args, self.root, self.outputs, datetime(2026, 1, 6))
        first = sha256(self.outputs / "场内账户_2025-12-30.xlsx")
        day = "2025-12-31"
        write_source(self.root / "flows" / f"{day}.xlsx", "flow", day, [
            record(day, "historical-edit", "BUYER", 1, 107),
        ])
        with (patch("account_daily_pnl.sources.BctClient", FakeBct),
              patch("account_daily_pnl.daily_cache.read_source", wraps=read_source) as load_flow):
            app.run(self.args, self.root, self.outputs, datetime(2026, 1, 6))
        self.assertEqual([call.args[2] for call in load_flow.call_args_list], [day, "2026-01-05"])
        self.assertEqual(self.summary("2026-01-05")["2602"]["单日盈亏"], 41)
        self.assertEqual(sha256(self.outputs / "场内账户_2025-12-30.xlsx"), first)

    def test_historical_mark_edit_revalues_two_days_without_reopening_flows(self):
        with patch("account_daily_pnl.sources.BctClient", FakeBct):
            app.run(self.args, self.root, self.outputs, datetime(2025, 12, 31))
            app.run(self.args, self.root, self.outputs, datetime(2026, 1, 6))
        day = "2025-12-31"
        write_source(self.root / "snapshots" / f"{day}.xlsx", "snapshot", day, [{
            "tradingDate": day, "instrumentId": "600000.SH", "instrumentQuote": 109,
            "currencyCode": "CNY", "netPosition": 12,
        }])
        with (patch("account_daily_pnl.sources.BctClient", FakeBct),
              patch("account_daily_pnl.daily_cache.read_source", wraps=read_source) as load_flow):
            app.run(self.args, self.root, self.outputs, datetime(2026, 1, 6))
        load_flow.assert_not_called()
        self.assertEqual(self.summary(day)["2602"]["单日盈亏"], -12)
        self.assertEqual(self.summary("2026-01-05")["2602"]["单日盈亏"], 26)

    def test_statement_equity_prefers_cash_adjusted_change_and_does_not_charge_fee_again(self):
        config = {
            "accounts": {"2602": {"cash_flows_confirmed_through": "2025-12-30"}},
            "cash_movements": [{"date": "2025-12-30", "account": "2602", "net_deposit": 10, "weight": 1}],
        }
        atomic_json(self.root / "inputs/config.local.json", config)
        write_book(self.root / "inputs/账户总权益.xlsx", [("结算单", ("交易日", "账户", "总权益"), [
            (date(2025, 12, 29), "2602", 1000), (date(2025, 12, 30), "2602", 1120),
        ])])
        self.args.only_day = True
        with patch("account_daily_pnl.sources.BctClient", FakeBct):
            app.run(self.args, self.root, self.outputs, datetime(2025, 12, 31))
        row = self.summary("2025-12-30")["2602"]
        self.assertEqual(row["期初总权益"], 1000)
        self.assertEqual(row["总权益"], 1120)
        self.assertEqual(row["当日手续费"], 1)
        self.assertEqual(row["成交估值净盈亏"], 109)
        self.assertEqual(row["单日盈亏"], 110)
        self.assertEqual(row["权益法减成交估值"], 1)
        self.assertEqual(row["基准以来累计净盈亏"], 110)
        self.assertAlmostEqual(row["日收益率"], 110 / 1010)
        self.assertEqual(row["盈亏来源"], "结算权益差")
        self.assertFalse((self.outputs / "逐交易日统计.xlsx").exists())
        self.assertFalse((self.outputs / SERIES_FILENAME).exists())

    def test_futures_legs_and_no_cash_bonus(self):
        self.baseline["positions"].append(
            {"account": "5526", "code": "IM2601.CFE", "side": "short", "quantity": 2, "price": 5000})
        ledger = Ledger(self.baseline)
        day = "2025-12-30"
        bonus = record(day, "bonus", "BUYER", 4, 0, fee=0)
        bonus["type"] = "BONUS"
        dividend = record(day, "dividend", "SELLER", 0, 0, fee=0, flag="CLOSE")
        dividend.update(type="DIVIDEND", dealBalance=5, dealBalanceWithFee=5)
        closing_short = record(day, "cover", "BUYER", 1, 5003, code="IM2601.CFE", account="5526", flag="CLOSE")
        new_long = record(day, "new", "BUYER", 3, 5003, code="IM2601.CFE", account="5526")
        result = ledger.advance(day, BASE_DAY, [bonus, dividend, closing_short, new_long])
        self.assertEqual(result.after["2602", "600000.SH"], (14, 0))
        self.assertEqual(result.after["5526", "IM2601.CFE"], (3, 1))
        self.assertEqual(result.movements["2602", "600000.SH"].cash, 5)
        self.assertFalse(result.current_issues)

    def test_same_day_long_and_short_round_trips_net_both_fees_without_marks(self):
        ledger = Ledger(self.baseline)
        day = "2025-12-30"
        common = {"code": "IM2601.CFE", "account": "5526"}
        frame = ledger.advance(day, BASE_DAY, [
            record(day, "long-open", "BUYER", 2, 5000, **common),
            record(day, "long-close", "SELLER", 2, 5003, flag="CLOSE", **common),
            record(day, "short-open", "SELLER", 1, 5010, **common),
            record(day, "short-close", "BUYER", 1, 5008, flag="CLOSE", **common),
        ])
        funding = app.funding_config({}, self.root / "inputs/账户总权益.xlsx")
        overview, _, _ = report(frame, ledger, self.baseline, {}, funding)
        result = next(row for row in overview if row["account"] == "5526")
        self.assertEqual(result["gross_pnl"], 1600)
        self.assertEqual(result["fees"], 4)
        self.assertEqual(result["pnl"], 1596)
        self.assertNotIn(("5526", "IM2601.CFE"), frame.after)

    def test_seed_is_verified_and_repeatable(self):
        for name in INPUTS[1:]:
            (self.root / name).write_bytes(b"sample-fixture")
        destination = Path(self.sandbox.name) / "seed.zip"
        with patch("account_daily_pnl.sources.BctClient", FakeBct):
            app.run(self.args, self.root, self.outputs, datetime(2025, 12, 31))
        make_seed(self.root, destination, ["2025-12-30"], {"2025-12-30"}, "2025-12-30")
        company = Path(self.sandbox.name) / "company"
        install_seed(company, destination)
        install_seed(company, destination)
        self.assertEqual(json.loads((company / "download_state.json").read_text(encoding="utf-8"))["latest_live_snapshot"],
                         "2025-12-30")
        self.assertEqual(sha256(company / "flows/2025-12-30.xlsx"), sha256(self.root / "flows/2025-12-30.xlsx"))

    def test_workbench_registration_updates_existing_task(self):
        class Workbench:
            def __init__(self):
                self.items = []

            def tasks(self):
                return self.items

            def save(self, value):
                value = dict(value)
                self.items = [item for item in self.items if item["id"] != value["id"]]
                self.items.append(value)
                return value

        work = Workbench()
        repo = Path(self.sandbox.name).resolve()
        definition = task_definition(repo, self.root, self.outputs, None, "09:25")
        saved, created = register_with_tasks(work, definition)
        self.assertTrue(created)
        self.assertTrue(saved["auto_catch_up"])
        self.assertEqual(saved["schedule"], {"type": "daily", "time": "09:25"})
        self.assertEqual(saved["result_mail"], "queue")
        self.assertEqual(saved["arguments"][:2], ["--no-pause", "--scheduled"])
        self.assertNotIn("--bct-script", saved["arguments"])
        saved["schedule"] = {"type": "weekdays", "time": "10:05"}
        saved["enabled"] = False
        saved["program"] = str(repo / "account_daily_pnl" / "start.cmd")
        existing, created = register_with_tasks(work, definition)
        self.assertFalse(created)
        self.assertTrue(existing["enabled"])
        self.assertEqual(existing["schedule"], {"type": "daily", "time": "09:25"})
        self.assertEqual(existing["result_mail"], "queue")
        self.assertEqual(existing["program"], definition["program"])
        self.assertEqual(len(work.items), 1)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_bct_credentials_are_encrypted_and_reusable_without_original_script(self):
        source = self.root / "inputs" / "fake.py"
        source.write_text("bct_username, bct_password = 'mock_user', 'mock_secret'\n", encoding="utf8")
        with patch("account_daily_pnl.setup_daily.BctClient") as client:
            configure_credentials(self.root, {}, source)
            client.assert_called_once_with(source)
        protected = bct_credential_path(self.root, {})
        raw = protected.read_text(encoding="utf8")
        self.assertIn("windows-dpapi-current-user-v1", raw)
        self.assertNotIn("mock_secret", raw)
        source.unlink()
        self.assertEqual(login_values(protected), ("mock_user", "mock_secret"))

    def test_scheduled_partial_report_has_distinct_exit_status(self):
        self.args.scheduled = True
        self.args.no_download = True
        self.args.date = "2025-12-30"
        with patch("account_daily_pnl.__main__.export_reports", return_value=None):
            self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2025, 12, 31)), 2)
        with patch("account_daily_pnl.__main__.export_reports", return_value=self.args.date):
            self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2025, 12, 31)), 0)

    def test_daily_falls_back_and_retries_when_bct_has_not_published_the_target(self):
        class DelayedBct(FakeBct):
            def snapshot(self, day):
                return []

        prior, target = "2025-12-30", "2025-12-31"
        state = self.root / "download_state.json"
        with patch("account_daily_pnl.sources.BctClient", FakeBct):
            self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2025, 12, 31)), 0)
        log = StringIO()
        with patch("account_daily_pnl.sources.BctClient", DelayedBct), redirect_stdout(log):
            self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2026, 1, 1)), 0)
        self.assertEqual(load_series(self.outputs / SERIES_FILENAME)["through"], prior)
        self.assertEqual(app.read_json(state)["latest_live_snapshot"], prior)
        self.assertFalse((self.root / "flows" / f"{target}.xlsx").exists())
        self.assertIn(f"账户收益截至 {prior}", log.getvalue())

        with patch("account_daily_pnl.sources.BctClient", FakeBct):
            self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2026, 1, 1)), 0)
        self.assertEqual(load_series(self.outputs / SERIES_FILENAME)["through"], target)
        self.assertEqual(app.read_json(state)["latest_live_snapshot"], target)
        self.assertEqual(read_source(self.root / "flows" / f"{target}.xlsx", "flow", target), [])

    def test_daily_falls_back_if_latest_flow_is_present_but_market_price_is_missing(self):
        prior, target = "2025-12-30", "2025-12-31"
        with patch("account_daily_pnl.sources.BctClient", FakeBct):
            self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2025, 12, 31)), 0)
        write_source(self.root / "flows" / f"{target}.xlsx", "flow", target, [])
        self.args.no_download = True
        self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2026, 1, 1)), 0)
        self.assertEqual(load_series(self.outputs / SERIES_FILENAME)["through"], prior)
        self.assertFalse((self.outputs / f"场内账户_{target}.xlsx").exists())

        self.args.no_download = False
        with patch("account_daily_pnl.sources.BctClient", FakeBct):
            self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2026, 1, 1)), 0)
        self.assertEqual(load_series(self.outputs / SERIES_FILENAME)["through"], target)
        self.assertEqual(self.summary(target)["2602"]["单日盈亏"], -24)

    def test_company_entry_only_configures_credentials_if_downloads_are_needed(self):
        self.args.company_run = True
        self.args.only_day = True
        client = FakeBct(None)
        with patch("account_daily_pnl.setup_daily.configure_credentials", return_value=client) as configure:
            self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2025, 12, 31)), 0)
            self.assertEqual(app.run(self.args, self.root, self.outputs, datetime(2025, 12, 31)), 0)
        self.assertEqual(configure.call_count, 1)
        self.assertTrue(configure.call_args.kwargs["allow_picker"])

    def test_wind_never_uses_a_different_date(self):
        class FakeWind:
            def __init__(self, config):
                pass

            def series(self, code, fields, start, end):
                return {"2025-12-30": {"close": 15}, "2025-12-31": {"close": 16}}

            def close(self):
                pass

        keys = {("2025-12-30", "600000.SH"), ("2026-01-05", "600000.SH")}
        prices, notes = resolve(keys, self.root, {}, provider_class=FakeWind)
        self.assertEqual(prices, {("2025-12-30", "600000.SH"): (15, "Wind:close")})
        self.assertFalse(notes)
        cached, notes = resolve(keys, self.root, {}, no_wind=True)
        self.assertEqual(cached, prices)
        self.assertTrue(notes)

    def test_wind_does_not_requery_cached_marks_or_span_across_them(self):
        calls = []
        class FakeWind:
            def __init__(self, config):
                pass

            def series(self, code, fields, start, end):
                calls.append((code, fields, start, end))
                return {start: {"close": 15}}

            def close(self):
                pass

        dates = ["2025-12-30", "2025-12-31", "2026-01-05"]
        code = "600000.SH"
        write_book(self.root / "wind/2025-12-31.xlsx", [("Wind日线", CACHE_COLUMNS, [
            ("2025-12-31", code, 22, "close", "Wind")
        ])])
        keys = {(day, code) for day in dates}
        prices, _ = resolve(keys, self.root, {}, provider_class=FakeWind, session_days=dates)
        self.assertEqual(len(prices), 3)
        self.assertEqual(calls, [(code, ["close"], dates[0], dates[0]), (code, ["close"], dates[2], dates[2])])
        self.assertEqual(resolve(keys, self.root, {}, provider_class=FakeWind, session_days=dates)[0], prices)
        self.assertEqual(len(calls), 2)

    def test_wind_keeps_both_fields_for_same_futures_contract_and_date(self):
        calls = []

        class FakeWind:
            def __init__(self, config):
                pass

            def series(self, code, fields, start, end):
                calls.extend(fields)
                return {start: {fields[0]: 5050}}

            def close(self):
                pass

        day, code = "2025-12-30", "IM2601.CFE"
        keys = {(day, code)}
        write_book(self.root / f"wind/{day}.xlsx", [("Wind日线", CACHE_COLUMNS, [
            (day, code, 5000, "settle", "Wind")
        ])])
        prices, _ = resolve(keys, self.root, {"wind_futures_field": "close"}, provider_class=FakeWind)
        self.assertEqual(prices[day, code], (5050, "Wind:close"))
        prices, _ = resolve(keys, self.root, {}, provider_class=FakeWind)
        self.assertEqual(prices[day, code], (5000, "Wind:settle"))
        self.assertEqual(calls, ["close"])

    def test_wind_log_distinguishes_legacy_cache_new_download_and_pending(self):
        class FakeWind:
            def __init__(self, config):
                pass

            def series(self, code, fields, start, end):
                return {start: {"close": 33}} if code == "600001.SH" else {}

            def close(self):
                pass

        day = "2025-12-30"
        write_book(self.root / f"wind/{day}.xlsx", [("Wind日线", CACHE_COLUMNS, [
            (day, "600000.SH", 20, "close", "Wind")
        ])])
        keys = {(day, code) for code in ("600000.SH", "600001.SH", "600002.SH")}
        log = StringIO()
        with redirect_stdout(log):
            prices, _ = resolve(keys, self.root, {}, provider_class=FakeWind, log_detail=True)
        self.assertEqual(set(prices), {(day, "600000.SH"), (day, "600001.SH")})
        for label, code in (("本地复用", "600000.SH"), ("新下载并保存", "600001.SH"), ("仍待补", "600002.SH")):
            self.assertIn(f"Wind {label}：1 项", log.getvalue())
            self.assertIn(f"{label} {day} close：{code}", log.getvalue())
        repeat = StringIO()
        with redirect_stdout(repeat):
            resolve(keys, self.root, {}, no_wind=True)
        self.assertIn("Wind 本地复用：2 项", repeat.getvalue())
        self.assertIn("Wind 新下载并保存：0 项", repeat.getvalue())


if __name__ == "__main__":
    unittest.main()
