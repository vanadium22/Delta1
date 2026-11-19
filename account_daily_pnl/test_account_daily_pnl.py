import argparse
from collections import Counter
from datetime import date, datetime
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
from account_daily_pnl.prices import resolve
from account_daily_pnl.seed import INPUTS, install_seed, make_seed
from account_daily_pnl.sources import read_source, write_book
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
                                       no_download=False, make_seed=None, prepare=False, only_day=False, no_wind=True)
        FakeBct.downloads.clear()

    def summary(self, day):
        path = self.outputs / f"场内账户_{day}.xlsx"
        data = load_workbook(path, read_only=True, data_only=True)
        try:
            header, *rows = data["账户统计"].values
            return {r[1]: dict(zip(header, r)) for r in rows}
        finally:
            data.close()

    def test_restart_backfills_skipped_trading_days(self):
        with patch("account_daily_pnl.sources.BctClient", FakeBct):
            app.run(self.args, self.root, self.outputs, datetime(2025, 12, 31))
            app.run(self.args, self.root, self.outputs, datetime(2026, 1, 6))
            digest = sha256(self.outputs / "场内账户_2026-01-05.xlsx")
            app.run(self.args, self.root, self.outputs, datetime(2026, 1, 6))
        days = ["2025-12-30", "2025-12-31", "2026-01-05"]
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


if __name__ == "__main__":
    unittest.main()
