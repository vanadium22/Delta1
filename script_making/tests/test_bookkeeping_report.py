"""Tests for explicit report references using synthetic, non-business IDs."""
import unittest
from decimal import Decimal

from script_making.bookkeeping_report import (report_backlinks, report_back_to_back_candidates,
                                              report_target_candidates, sum_candidate_quantities)


def table_and_row(headers, rows, selected=0):
    table = {"columns": [{"id": f"c{i}", "name": name, "type": "text"}
                         for i, name in enumerate(headers)],
             "rows": rows, "source_rows": [i + 2 for i in range(len(rows))]}
    row = {"excel_row": table["source_rows"][selected], "values": rows[selected]}
    return table, row


class ExplicitReportBacklinkTests(unittest.TestCase):
    def test_cross_report_target_is_an_explicit_exact_proposal(self):
        source, selected = table_and_row(["协议编号", "标的"], [["CONF-A", "000001.SZ"]])
        target, _ = table_and_row(["合约编号", "交易确认书编号", "标的物代码", "标的物名称"],
                                  [["A", "CONF-A", "000001.SZ", "示例一"],
                                   ["A", "CONF-A", "600000.SH", "示例二"],
                                   ["B", "CONF-B", "000001.SZ", "示例一"]])
        result = report_target_candidates(source, selected, target)
        self.assertEqual(result["state"], "matched")
        self.assertEqual((result["source_field"], result["target_field"]), ("协议编号", "交易确认书编号"))
        self.assertTrue(result["underlying_matched"])
        self.assertEqual([row["excel_row"] for row in result["rows"]], [2])
        selected["values"] = ["CONF-A", "UNKNOWN"]
        result = report_target_candidates(source, selected, target)
        self.assertFalse(result["underlying_matched"])
        self.assertEqual([row["excel_row"] for row in result["rows"]], [2, 3])
        selected["values"] = ["CONF-NOT-FOUND", "000001.SZ"]
        self.assertEqual(report_target_candidates(source, selected, target)["state"], "not_found")

    def test_cross_report_target_does_not_guess_ambiguous_columns_or_zero(self):
        source, row = table_and_row(["协议编号", "协议编号"], [["A", "B"]])
        target, _ = table_and_row(["交易确认书编号"], [["A"]])
        self.assertEqual(report_target_candidates(source, row, target)["state"], "source_ambiguous")
        source, row = table_and_row(["协议编号"], [[0]])
        self.assertEqual(report_target_candidates(source, row, target)["state"], "no_identifier")
        source, row = table_and_row(["协议编号"], [["A"]])
        target, _ = table_and_row(["交易确认书编号", "交易确认书编号"], [["A", "A"]])
        self.assertEqual(report_target_candidates(source, row, target)["state"], "target_ambiguous")

    def test_each_field_matches_all_rows_by_its_own_exact_identifier(self):
        headers = ["合约编号", "交易确认书编号", "标的物代码", "关联背靠背合约", "关联背靠背确认书编号"]
        rows = [["A", "CONF-A", "A.SZ", "B", "CONF-B"],
                ["B", "CONF-B", "B1.SZ", "", ""],
                ["B", "CONF-B", "B2.SZ", "", ""],
                ["B-EXTRA", "CONF-B-EXTRA", "OTHER", "", ""]]
        table, row = table_and_row(headers, rows)
        result = report_backlinks(table, row)
        self.assertEqual([field["state"] for field in result["fields"]], ["matched", "matched"])
        self.assertEqual(result["fields"][0]["target_id"], "B")
        self.assertEqual(result["fields"][1]["target_id"], "CONF-B")
        for field in result["fields"]:
            self.assertEqual([match["excel_row"] for match in field["matches"]], [3, 4])
            self.assertFalse(field["self_reference"])
        self.assertEqual(result["columns"], table["columns"])

    def test_missing_target_keeps_explicit_source_identifier_visible(self):
        table, row = table_and_row(["合约编号", "关联背靠背合约"], [["A", "MISSING"]])
        field, missing_source = report_backlinks(table, row)["fields"]
        self.assertEqual(field["state"], "not_found")
        self.assertEqual(field["target_id"], "MISSING")
        self.assertEqual(field["matches"], [])
        self.assertEqual(missing_source["state"], "source_missing")

    def test_placeholders_zero_and_excel_errors_never_become_references(self):
        headers = ["合约编号", "关联背靠背合约"]
        for value, expected in [(None, "empty"), ("  ", "empty"), (0, "zero"), (0.0, "zero"),
                                ("000", "zero"), ("0.00", "zero"), ("#N/A", "excel_error"),
                                ("#REF!", "excel_error"), ("N/A", "placeholder"),
                                ("无", "placeholder"), (float("nan"), "invalid"), (False, "invalid"),
                                (Decimal("0E-8"), "zero"), (Decimal("sNaN"), "invalid")]:
            with self.subTest(value=value):
                table, row = table_and_row(headers, [["A", value], ["0", "A"]])
                field = report_backlinks(table, row)["fields"][0]
                self.assertEqual(field["state"], "no_value")
                self.assertEqual(field["source_value_kind"], expected)
                self.assertIsNone(field["target_id"])
                self.assertEqual(field["matches"], [])

    def test_missing_or_duplicate_source_and_target_columns_are_not_guessed(self):
        cases = [(["合约编号"], ["A"], "source_missing"),
                 (["关联背靠背合约", "关联背靠背合约", "合约编号"], ["B", "B", "A"], "source_ambiguous"),
                 (["关联背靠背合约"], ["B"], "target_missing"),
                 (["关联背靠背合约", "合约编号", "合约编号"], ["B", "B", "A"], "target_ambiguous")]
        for headers, values, expected in cases:
            with self.subTest(expected=expected):
                table, row = table_and_row(headers, [values])
                field = report_backlinks(table, row)["fields"][0]
                self.assertEqual(field["state"], expected)
                self.assertEqual(field["matches"], [])

    def test_exact_matching_preserves_leading_zeros_and_case(self):
        headers = ["合约编号", "关联背靠背合约"]
        rows = [["BASE", "0001A"], ["0001A", ""], ["1A", ""], ["0001a", ""], ["0001A-extra", ""]]
        table, row = table_and_row(headers, rows)
        field = report_backlinks(table, row)["fields"][0]
        self.assertEqual([match["excel_row"] for match in field["matches"]], [3])

    def test_independent_references_and_self_reference_remain_visible(self):
        headers = ["合约编号", "交易确认书编号", "关联背靠背合约", "关联背靠背确认书编号"]
        rows = [["A", "CONF-A", "A", "CONF-C"], ["B", "CONF-B", "", ""], ["C", "CONF-C", "", ""]]
        table, row = table_and_row(headers, rows)
        left, right = report_backlinks(table, row)["fields"]
        self.assertTrue(left["self_reference"])
        self.assertEqual([match["excel_row"] for match in left["matches"]], [2])
        self.assertFalse(right["self_reference"])
        self.assertEqual([match["excel_row"] for match in right["matches"]], [4])

    def test_malformed_input_fails_without_partial_matches(self):
        table, row = table_and_row(["合约编号", "关联背靠背合约"], [["A", "B"], ["B"]])
        with self.assertRaisesRegex(ValueError, "字段不完整"):
            report_backlinks(table, row)
        table["source_rows"] = [2]
        with self.assertRaisesRegex(ValueError, "不完整"):
            report_backlinks(table, row)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.headers = ["合约编号", "标的物代码", "交易对手名称", "标的名义数量",
                        "交易达成日", "起始日", "开仓操作人员", "我方资产方向"]
        self.rows = [
            ["A", "000001.SZ", "内台甲", "0.1", "2026-01-02", "2026-01-03", "M1", "多"],
            ["A", "000001.SZ", "内台甲", "0.2", "2026-01-02", "2026-01-03", "M1", "多"],
            ["A", "600000.SH", "内台甲", "3", "2026-01-02", "2026-01-03", "M1", "多"],
            ["A", None, "内台甲", "10", "2026-01-02", "2026-01-03", "M1", "多"],
            ["B", "000001.SZ", "内台乙", "0.1", "2026-01-02", "2026-01-03", "M1", "空"],
            ["B", "000001.SZ", "内台乙", "0.2", "2026-01-02", "2026-01-03", "M1", "空"],
            ["C", "000001.SZ", "内台乙", "3", "2026-01-05", "2026-01-06", "M2", "空"],
            ["D", "000001.SZ", "外部客户", "0.3", "2026-01-02", "2026-01-03", "M1", "空"],
            ["E", "000001.SZ", "内台乙", None, None, None, None, "空"],
            ["E", "000001.SZ", "内台乙", "5", None, None, None, "空"],
            ["F", "000001.SZ.X", "内台乙", "0.3", "2026-01-02", "2026-01-03", "M1", "空"],
            ["G", "000001.SZ", "内台乙附属", "0.3", "2026-01-02", "2026-01-03", "M1", "空"],
            [None, "000001.SZ", "内台乙", "0.3", "2026-01-02", "2026-01-03", "M1", "空"],
            ["H", "600000.SH", "内台乙", "0", "2026-01-05", "2026-01-06", "M2", "空"],
        ]
        self.table, _ = table_and_row(self.headers, self.rows)

    def test_all_underlyings_explicit_internal_desks_and_multi_rows(self):
        result = report_back_to_back_candidates(self.table, "A", {"内台甲", "内台乙"})
        self.assertEqual(result["state"], "ok")
        self.assertEqual([group["code"] for group in result["underlyings"]], ["000001.SZ", "600000.SH", None])
        self.assertEqual([row["excel_row"] for row in result["target_rows"]], [2, 3, 4, 5])
        first, second, missing = result["underlyings"]
        self.assertEqual(first["target_quantity"]["value"], "0.3")
        self.assertEqual([item["contract_id"] for item in first["candidates"]], ["B", "C", "E"])
        first_match = first["candidates"][0]
        self.assertEqual([row["excel_row"] for row in first_match["rows"]], [6, 7])
        self.assertEqual(first_match["quantity"]["value"], "0.3")
        self.assertEqual(first_match["comparisons"], {"quantity": "same", "trade_date": "same",
                            "start_date": "same", "operator": "same", "direction": "different"})
        self.assertEqual([item["contract_id"] for item in second["candidates"]], ["H"])
        self.assertEqual(second["candidates"][0]["quantity"]["value"], "0")
        self.assertEqual(missing["candidates"], [])
        self.assertEqual([r["excel_row"] for r in result["unusable_candidate_rows"]], [14])
        self.assertEqual([r["excel_row"] for r in first["unusable_candidate_rows"]], [14])
        self.assertEqual(second["unusable_candidate_rows"], [])

    def test_missing_values_are_not_zero_and_do_not_exclude_candidate(self):
        result = report_back_to_back_candidates(self.table, "A", ["内台乙"])
        candidates = result["underlyings"][0]["candidates"]
        item = next(item for item in candidates if item["contract_id"] == "E")
        self.assertEqual(item["quantity"]["value"], None)
        self.assertEqual(item["quantity"]["known_value"], "5")
        self.assertEqual(item["quantity"]["missing_count"], 1)
        self.assertFalse(item["quantity"]["complete"])
        self.assertEqual(item["comparisons"]["quantity"], "missing")
        self.assertEqual(item["comparisons"]["trade_date"], "missing")
        self.assertEqual(item["comparisons"]["operator"], "missing")
        self.assertIn("C", [candidate["contract_id"] for candidate in candidates])

    def test_exact_decimal_totals_do_not_follow_global_precision(self):
        rows = [["A", "X", "客户", "10000000000000000000000000000", "d", "d", "a", "多"],
                ["A", "X", "客户", "0.00000000000000000000000000001", "d", "d", "a", "多"],
                ["B", "X", "内台", "10000000000000000000000000000.00000000000000000000000000001", "d", "d", "a", "空"]]
        table, _ = table_and_row(self.headers, rows)
        result = report_back_to_back_candidates(table, "A", ["内台"])
        item = result["underlyings"][0]
        self.assertEqual(item["target_quantity"]["value"], "10000000000000000000000000000.00000000000000000000000000001")
        self.assertEqual(item["candidates"][0]["comparisons"]["quantity"], "same")

    def test_exact_sum_across_candidate_groups_propagates_missing(self):
        groups = [{"quantity": {"value": "10000000000000000000000000000", "complete": True}},
                  {"quantity": {"value": "0.00000000000000000000000000001", "complete": True}}]
        aggregate = sum_candidate_quantities(groups)
        self.assertEqual(aggregate["value"], "10000000000000000000000000000.00000000000000000000000000001")
        self.assertTrue(aggregate["complete"])
        groups.append({"quantity": {"value": None, "known_value": "5", "complete": False}})
        aggregate = sum_candidate_quantities(groups)
        self.assertIsNone(aggregate["value"])
        self.assertEqual(aggregate["missing_count"], 1)
        self.assertFalse(aggregate["complete"])

    def test_incomplete_target_and_missing_optional_fields_remain_distinct(self):
        rows = [["A", "X", "客户", "NaN"], ["A", "X", "客户", "5"], ["B", "X", "内台", "3"]]
        table, _ = table_and_row(self.headers[:4], rows)
        result = report_back_to_back_candidates(table, "A", ["内台"])
        group = result["underlyings"][0]
        self.assertIsNone(group["target_quantity"]["value"])
        self.assertEqual(group["target_quantity"]["known_value"], "5")
        self.assertEqual(group["target_quantity"]["missing_count"], 1)
        self.assertEqual(group["candidates"][0]["comparisons"]["quantity"], "missing")
        self.assertEqual(group["candidates"][0]["comparisons"]["operator"], "missing")
        self.assertIn({"field": "开仓操作人员", "reason": "missing"}, result["issues"])

    def test_missing_ambiguous_columns_and_desks_do_not_guess(self):
        empty_desks = report_back_to_back_candidates(self.table, "A", [])
        self.assertEqual(empty_desks["state"], "missing_desks")
        self.assertEqual(len(empty_desks["target_rows"]), 4)
        self.assertEqual([item["code"] for item in empty_desks["underlyings"]], ["000001.SZ", "600000.SH", None])
        self.assertEqual(report_back_to_back_candidates(self.table, "A", "内台乙")["state"], "missing_desks")
        self.assertEqual(report_back_to_back_candidates(self.table, "0", ["内台乙"])["state"], "invalid_contract")
        self.assertEqual(report_back_to_back_candidates(self.table, "a", ["内台乙"])["state"], "target_not_found")
        for headers, rows in [(["合约编号", "合约编号", "标的物代码", "交易对手名称"], [["A", "B", "X", "客户"]]),
                              (["合约编号", "标的物代码", "标的物代码", "交易对手名称"], [["A", "X", "Y", "客户"]]),
                              (["合约编号", "标的物代码"], [["A", "X"]])]:
            with self.subTest(headers=headers):
                table, _ = table_and_row(headers, rows)
                result = report_back_to_back_candidates(table, "A", ["内台"])
                self.assertEqual(result["state"], "missing_columns")
                self.assertFalse(any(group["candidates"] for group in result["underlyings"]))


if __name__ == "__main__":
    unittest.main()
