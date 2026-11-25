from datetime import date
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from openpyxl import load_workbook

from account_daily_pnl import trade_summary as app
from account_daily_pnl.setup_daily import register_with_tasks, task_definition as morning_task_definition
from account_daily_pnl.test_account_daily_pnl import record
from shared_data.io import sha256


DAY = date(2026, 11, 25)


class TradeSummaryTests(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory(dir=os.environ.get("ACCOUNT_PNL_TEST_DIR"))
        self.addCleanup(scratch.cleanup)
        self.repo = Path(scratch.name)
        self.data = self.repo / "data"
        self.outputs = self.repo / "outputs"

    def trade(self, identifier, direction, quantity, price, **kwargs):
        return record(DAY.isoformat(), identifier, direction, quantity, price, **kwargs)

    def run_day(self, rows, result=None, recipients=None):
        client = Mock()
        client.flows.return_value = rows
        with patch.object(app, "configure_credentials", return_value=client) as setup:
            book = app.run_day(DAY, self.data, self.outputs, None, None, scheduled=True,
                               recipients=recipients, wa_output=result)
        setup.assert_called_once_with(self.data, {}, None, allow_picker=False)
        client.flows.assert_called_once_with([DAY.isoformat()])
        return book

    def test_same_day_workbook_groups_actual_trades_by_instrument_direction_and_currency(self):
        rows = [
            self.trade("b1", "BUYER", 10, 9, fee=7),
            self.trade("b2", "BUYER", 5, 8),
            self.trade("s1", "SELLER", 2, 11, fee=5),
            self.trade("a2", "SELLER", 3, 9, account="5526"),
            self.trade("f1", "BUYER", 2, 4000, code="IM2612.CFE", account="5524", flag="CLOSE"),
            {**self.trade("usd", "BUYER", 1, 1), "currencyCode": "USD"},
            {**self.trade("bonus", "BUYER", 2, 10), "type": "BONUS"},
            {**self.trade("missing", "BUYER", 1, 10), "tradeAccount": None},
            {**self.trade("other", "BUYER", 1, 10), "tradeAccount": "OTHER"},
        ]
        result = self.repo / "result.json"
        recipients = ["first@example.invalid", "second@example.invalid"]
        book = self.run_day(rows, result, recipients)
        data = load_workbook(book, data_only=True)
        try:
            self.assertEqual(data.sheetnames, ["三账户合计", "2602", "5526", "5524", "取数说明"])
            values = list(data["三账户合计"].values)
            self.assertEqual(values[0], app.COLUMNS)
            self.assertEqual([row[1:] for row in values[1:]], [
                ("600000.SH", "买入", 15, "CNY", 130, 2),
                ("600000.SH", "买入", 1, "USD", 1, 1),
                ("600000.SH", "卖出", -5, "CNY", 49, 2),
                ("IM2612.CFE", "买入", 2, "CNY", 1600000, 1),
            ])
            self.assertTrue(all(row[0].date() == DAY for row in values[1:]))
            summary = data["三账户合计"]
            self.assertEqual(summary.auto_filter.ref, "A1:G5")
            self.assertEqual(summary["B2"].fill.fgColor.rgb, summary["B4"].fill.fgColor.rgb)
            self.assertNotEqual(summary["B4"].fill.fgColor.rgb, summary["B5"].fill.fgColor.rgb)
            self.assertEqual(summary["C2"].font.color.rgb, "FFA6293B")
            self.assertEqual(summary["C4"].font.color.rgb, "FF176648")
            self.assertEqual(summary["D4"].font.color.rgb, summary["C4"].font.color.rgb)
            self.assertEqual(data["5526"]["C2"].font.color.rgb, "FF176648")
            self.assertEqual(list(data["5526"].values)[1][3:], (-3, "CNY", 27, 1))
            checks = dict(data["取数说明"].values)
            self.assertEqual([checks[key] for key in ("已纳入成交笔数", "排除的非成交记录",
                                                       "其他账户成交笔数", "交易账户缺失笔数")], [6, 1, 1, 1])
        finally:
            data.close()
        self.assertTrue((self.data / "trade_summary/flows" / f"{DAY}.xlsx").is_file())
        self.assertFalse((self.data / "flows").exists())
        first = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(first["mail"]["to"], recipients)
        self.assertIn(DAY.isoformat(), first["mail"]["subject"])
        attachment, = first["mail"]["attachments"]
        self.assertEqual((attachment["path"], attachment["sha256"]), (str(book), sha256(book)))

        self.assertEqual(self.run_day(list(reversed(rows)), result, recipients), book)
        self.assertEqual(json.loads(result.read_text(encoding="utf-8")), first)
        self.assertEqual(self.run_day(rows, result, [recipients[1]]), book)
        self.assertNotEqual(json.loads(result.read_text(encoding="utf-8"))["delivery_key"], first["delivery_key"])

    def test_empty_day_exports_empty_summaries_but_other_dates_fail(self):
        book = self.run_day([])
        data = load_workbook(book, read_only=True, data_only=True)
        try:
            self.assertEqual(list(data["三账户合计"].values), [app.COLUMNS])
        finally:
            data.close()
        old_trade = {**self.trade("yesterday", "BUYER", 1, 10), "tradingDate": "2026-11-24"}
        result = self.repo / "wrong-date-result.json"
        with self.assertRaisesRegex(ValueError, "异常日期"):
            self.run_day([old_trade], result, ["first@example.invalid"])
        self.assertFalse(result.exists())
        self.assertTrue(book.is_file())

    def test_configurable_recipients_and_separate_workbench_registration(self):
        config = self.repo / "account_daily_pnl" / app.MAIL_CONFIG
        with patch.object(app, "REPO", self.repo), patch.object(app, "register_task") as register:
            register.side_effect = lambda _, definition: (definition, True)
            self.assertEqual(app.main(["--setup", "--work-root", str(self.repo), "--set-recipients",
                                       "a@example.invalid，b@example.invalid,a@example.invalid"]), 0)
            self.assertEqual(app.read_recipients(config), ["a@example.invalid", "b@example.invalid"])
            self.assertEqual(app.main(["--set-recipients", "updated@example.invalid"]), 0)
            self.assertEqual(app.read_recipients(config), ["updated@example.invalid"])
            self.assertEqual(app.main(["--set-recipients", "broken"]), 1)
            self.assertEqual(app.read_recipients(config), ["updated@example.invalid"])
        register.assert_called_once()
        afternoon = register.call_args.args[1]
        morning = morning_task_definition(self.repo, self.data, self.outputs, None, "09:25")
        tasks = Mock()
        tasks.tasks.return_value = [morning]
        tasks.save.side_effect = lambda definition: definition
        saved, created = register_with_tasks(tasks, afternoon)
        self.assertTrue(created)
        self.assertNotEqual(saved["id"], morning["id"])
        self.assertEqual(saved["schedule"], {"type": "daily", "time": "15:30"})
        self.assertFalse(saved["auto_catch_up"])
        self.assertEqual(saved["result_mail"], "queue")
        self.assertEqual(Path(saved["program"]).name, "trade_summary.py")
        self.assertNotIn("a@example.invalid", saved["arguments"])


if __name__ == "__main__":
    unittest.main()
