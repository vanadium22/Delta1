"""Manual records and explicit counterpart links: synthetic data only."""
import hashlib
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from script_making.bookkeeping import BookkeepingStore
from script_making.storage import ReportError


def ref(contract_no="", confirmation_no="", code="000001.SZ", **kwargs):
    return {"contract_no": contract_no, "confirmation_no": confirmation_no,
            "underlying_code": code, **kwargs}


class BookkeepingTests(unittest.TestCase):
    def setUp(self):
        cache = Path(__file__).resolve().parents[1] / "cache" / "bookkeeping-tests"
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.root = Path(self.temp.name)
        self.store = BookkeepingStore(self.root / "data" / "manual.sqlite3")
        self.base = {"action": "open", "trade_date": "2026-10-28", "contract_no": "SYN-1",
                     "confirmation_no": "TEST-1", "counterparty": "示例对手",
                     "underlying_code": "000001.SZ", "underlying_name": "示例标的",
                     "direction": "多头", "amount": "0.100000000000000001", "quantity": "1,234.50",
                     "price": "1.234567890123456789", "unit": "股", "note": "人工登记",
                     "source": {"date": "2026-10-27", "filename": "sample.xlsx", "sheet": "存续合约估值",
                                "excel_row": 4, "fields": [{"name": "合约编号", "value": "SYN-1"}]}}

    def tearDown(self):
        self.temp.cleanup()

    def test_read_empty_does_not_create_file(self):
        self.assertEqual(self.store.list_records(), [])
        self.assertEqual(self.store.get_back_to_back({"contract_no": "SYN-1"})["status"], "unknown")
        self.assertIsNone(self.store.get_record("missing"))
        self.assertFalse(self.store.path.exists())

    def test_identity_does_not_merge_identifiers_with_different_case(self):
        self.store.link_contracts(ref("ABC-1", "CONF-1"), ref("PAIR-1"))
        self.assertEqual(self.store.get_back_to_back(ref("ABC-1"))["status"], "linked")
        self.assertEqual(self.store.get_back_to_back(ref("abc-1"))["status"], "unknown")
        self.assertEqual(self.store.get_back_to_back(ref("ABC-1", code="000001.sz"))["status"], "unknown")

    def test_operation_group_identity_and_name_are_persisted_together(self):
        record = self.store.save_record({**self.base, "group_id": "synthetic-group", "group_name": "一并开平"})
        self.assertEqual(self.store.get_record(record["id"])["group_name"], "一并开平")
        self.assertEqual(self.store.list_records("一并开平")[0]["id"], record["id"])
        with self.assertRaisesRegex(ReportError, "操作组"):
            self.store.save_record({**self.base, "group_id": "missing-name"})

    def test_new_edit_snapshot_exact_decimal_and_revision(self):
        record = self.store.save_record(self.base)
        self.assertEqual(record["version"], 1)
        self.assertEqual(record["price"], "1.234567890123456789")
        self.assertEqual(record["amount"], "0.100000000000000001")
        self.assertEqual(record["source"], self.base["source"])
        second = self.store.save_record({**record, "amount": "123.000000000000001", "note": "更新"},
                                        record_id=record["id"], expected_version=record["version"])
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["source"], self.base["source"])
        self.assertEqual(self.store.get_record(record["id"])["amount"], "123.000000000000001")
        self.assertEqual([r["version"] for r in self.store.record_history(record["id"])], [1, 2])
        with self.assertRaisesRegex(ReportError, "刷新"):
            self.store.save_record({**record, "amount": "99"}, record_id=record["id"], expected_version=1)
        self.assertEqual(self.store.get_record(record["id"])["amount"], "123.000000000000001")

    def test_source_snapshot_cannot_be_silently_replaced(self):
        record = self.store.save_record(self.base)
        edited = {**record, "source": {"date": "2026-10-28"}}
        with self.assertRaisesRegex(ReportError, "来源快照"):
            self.store.save_record(edited, record_id=record["id"], expected_version=1)
        edited.pop("source")
        self.assertEqual(self.store.save_record(edited, record_id=record["id"], expected_version=1)["source"], self.base["source"])

    def test_status_and_symmetric_report_relationship(self):
        left = ref("SYN-1", "TEST-1", source={"date": "2026-10-27", "sheet": "合成表", "excel_row": 3})
        right = ref("SYN-2", "TEST-2", counterparty="示例台", source={"date": "2026-10-27", "sheet": "合成表", "excel_row": 4})
        self.assertEqual(self.store.set_back_status(left, "none")["status"], "none")
        self.store.link_contracts(left, right, "用户指定")
        self.assertEqual(self.store.get_back_to_back(ref(confirmation_no="TEST-1"))["status"], "linked")
        self.assertEqual(self.store.get_back_to_back(ref("SYN-2"))["status"], "linked")
        back = self.store.get_back_to_back(ref("SYN-1"))["counterparts"][0]
        self.assertEqual(back["ref"]["contract_no"], "SYN-2")
        self.assertEqual(back["link_snapshot"]["source"]["excel_row"], 4)
        with self.assertRaisesRegex(ReportError, "先解除"):
            self.store.set_back_status(left, "none")
        self.assertTrue(self.store.unlink_contracts(left, right))
        self.assertEqual(self.store.get_back_to_back(left)["status"], "unknown")
        self.assertEqual(self.store.set_back_status(left, "none")["status"], "none")

    def test_original_reference_snapshot_survives_later_report_update(self):
        left = ref("SYN-1", source={"date": "2026-10-27"})
        right = ref("SYN-2", source={"date": "2026-10-27"})
        self.store.link_contracts(left, right)
        self.store.link_contracts({**left, "source": {"date": "2026-10-28"}},
                                  {**right, "source": {"date": "2026-10-28"}})
        back = self.store.get_back_to_back(left)["counterparts"][0]
        self.assertEqual(back["ref"]["source"]["date"], "2026-10-27")
        self.assertEqual(back["link_snapshot"]["source"]["date"], "2026-10-27")

    def test_unassigned_open_can_later_gain_identifier_without_losing_link(self):
        record = self.store.save_record({"action": "open", "trade_date": "2026-10-28", "note": "待编号"})
        self.assertTrue(record["local_id"])
        self.store.link_contracts({"local_id": record["local_id"]}, ref("SYN-2"))
        updated = self.store.save_record({**record, "contract_no": "SYN-1", "underlying_code": "000001.SZ"}, record_id=record["id"], expected_version=1)
        self.assertEqual(updated["local_id"], record["local_id"])
        self.assertEqual(self.store.get_back_to_back(ref("SYN-1"))["status"], "linked")
        self.assertEqual(self.store.get_back_to_back({"local_id": record["local_id"]})["status"], "linked")
        with self.assertRaisesRegex(ReportError, "不能更改"):
            self.store.save_record({**updated, "contract_no": "DIFFERENT"}, record_id=record["id"], expected_version=2)
        self.assertEqual(self.store.get_back_to_back(ref("SYN-1"))["status"], "linked")

    def test_search_includes_back_contract_and_source(self):
        record = self.store.save_record(self.base)
        self.store.link_contracts(ref("SYN-1"), ref("PAIR-EXAMPLE"))
        self.assertEqual(self.store.list_records("pair-example")[0]["id"], record["id"])
        self.assertEqual(self.store.list_records("sample.xlsx")[0]["id"], record["id"])
        self.assertEqual(self.store.list_records("not-found"), [])

    def test_conflicting_identifiers_and_self_link_rollback(self):
        self.store.link_contracts(ref("SYN-1", "TEST-1"), ref("SYN-2"))
        self.store.set_back_status(ref("SYN-3", "TEST-3"), "none")
        with self.assertRaisesRegex(ReportError, "不同已登记"):
            self.store.link_contracts(ref("SYN-1", "TEST-3"), ref("SYN-4"))
        with self.assertRaisesRegex(ReportError, "同一合约"):
            self.store.link_contracts(ref("SYN-1"), ref(confirmation_no="TEST-1"))
        self.assertEqual(self.store.get_back_to_back(ref("SYN-1"))["status"], "linked")
        self.assertEqual(self.store.get_back_to_back(ref("SYN-3"))["status"], "none")

    def test_same_contract_numbers_for_distinct_underlyings_are_separate(self):
        self.store.link_contracts(ref("SHARED", "CONF", code="000001.SZ"), ref("PAIR-A", code="000001.SZ"))
        self.store.link_contracts(ref("SHARED", "CONF", code="600000.SH"), ref("PAIR-B", code="600000.SH"))
        first = self.store.get_back_to_back(ref("SHARED", code="000001.SZ"))
        second = self.store.get_back_to_back(ref("SHARED", code="600000.SH"))
        self.assertEqual(first["counterparts"][0]["ref"]["contract_no"], "PAIR-A")
        self.assertEqual(second["counterparts"][0]["ref"]["contract_no"], "PAIR-B")
        incomplete = self.store.get_back_to_back({"contract_no": "SHARED"})
        self.assertEqual(incomplete["status"], "unknown")
        self.assertTrue(incomplete["requires_underlying"])
        self.assertEqual(incomplete["counterparts"], [])
        self.assertEqual({item["underlying_code"] for item in incomplete["candidates"]}, {"000001.SZ", "600000.SH"})
        with self.assertRaisesRegex(ReportError, "标的代码"):
            self.store.link_contracts({"contract_no": "SHARED"}, ref("PAIR-C"))

    def test_same_confirmation_and_underlying_conflicting_contract_rejected(self):
        self.store.link_contracts(ref("A", "CONF"), ref("PAIR"))
        with self.assertRaisesRegex(ReportError, "冲突"):
            self.store.link_contracts(ref("B", "CONF"), ref("OTHER"))
        self.assertEqual(self.store.get_back_to_back(ref("A", "CONF"))["status"], "linked")

    def test_invalid_fields_and_unidentified_close_do_not_create_record(self):
        for value in ("NaN", "Infinity", "bad"):
            with self.subTest(value=value), self.assertRaises(ReportError):
                self.store.save_record({**self.base, "amount": value})
        with self.assertRaisesRegex(ReportError, "请选择新开"):
            self.store.save_record({**self.base, "action": "bad"})
        with self.assertRaisesRegex(ReportError, "平仓请先"):
            self.store.save_record({"action": "close", "trade_date": "2026-10-28"})
        self.assertFalse(self.store.path.exists())

    def test_unknown_database_is_never_modified(self):
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_bytes(b"an unrelated existing file")
        before = hashlib.sha256(self.store.path.read_bytes()).hexdigest()
        with self.assertRaises(ReportError):
            self.store.save_record(self.base)
        self.assertEqual(hashlib.sha256(self.store.path.read_bytes()).hexdigest(), before)

    def test_unrelated_database_with_same_schema_version_is_never_modified(self):
        self.store.path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.store.path)) as connection:
            connection.execute("CREATE TABLE meta(key TEXT,value TEXT)")
            connection.execute("INSERT INTO meta VALUES('schema_version','1')")
            connection.execute("CREATE TABLE other(value TEXT)")
            connection.execute("INSERT INTO other VALUES('keep')")
            connection.commit()
        before = hashlib.sha256(self.store.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ReportError, "不兼容"):
            self.store.save_record(self.base)
        self.assertEqual(hashlib.sha256(self.store.path.read_bytes()).hexdigest(), before)

    def test_concurrent_writes_keep_all_records(self):
        barrier = threading.Barrier(8)
        failures = []
        def save(number):
            try:
                barrier.wait()
                BookkeepingStore(self.store.path).save_record({**self.base, "contract_no": f"SYN-{number}",
                                                              "confirmation_no": f"TEST-{number}"})
            except Exception as exc:
                failures.append(exc)
        threads = [threading.Thread(target=save, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(failures, failures)
        self.assertEqual(len(self.store.list_records()), 8)

    def test_concurrent_edits_require_fresh_version(self):
        record = self.store.save_record(self.base)
        barrier = threading.Barrier(2)
        outcomes = []
        def save(note):
            barrier.wait()
            try:
                saved = BookkeepingStore(self.store.path).save_record({**record, "note": note},
                                                                     record_id=record["id"], expected_version=1)
                outcomes.append(("ok", saved["note"]))
            except ReportError:
                outcomes.append(("conflict", note))
        threads = [threading.Thread(target=save, args=(str(i),)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        self.assertEqual(sorted(item[0] for item in outcomes), ["conflict", "ok"])
        self.assertEqual(len(self.store.record_history(record["id"])), 2)

    def test_separate_processes_write_without_losing_records(self):
        program = ("import sys; from script_making.bookkeeping import BookkeepingStore; "
                   "BookkeepingStore(sys.argv[1]).save_record({'action':'open',"
                   "'trade_date':'2026-10-28','contract_no':'PROCESS-'+sys.argv[2]})")
        processes = [subprocess.Popen([sys.executable, "-X", "utf8", "-c", program, str(self.store.path), str(i)],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(3)]
        for process in processes:
            _, error = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, error.decode("utf-8", errors="replace"))
        self.assertEqual(len(self.store.list_records()), 3)


if __name__ == "__main__":
    unittest.main()
