"""Daily volume gap filling without rewriting existing observations."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from index_futures_basis.store import Store
from index_futures_basis.recent_brief.refresh import refresh_volumes


class DailyVolumeTests(unittest.TestCase):
    def seed(self, path):
        store = Store(path)
        days = ["2026-01-02", "2026-01-05"]
        store.save_calendar(days[0], days[-1], days)
        mappings = [(day, root, slot, f"{root}26{slot+1:02d}.CFE")
                    for day in days for root in ("IF", "IH", "IC", "IM") for slot in range(1, 5)]
        store.save_rows("mapping", mappings)
        store.save_rows("quotes", [(code, day, "volume", 123.) for day, root, slot, code in mappings
                                  if (day, root, slot) != (days[-1], "IF", 1)])
        return SimpleNamespace(store=store, config={}, window=lambda _: (days[0], days[-1]))

    def test_only_missing_actual_contract_volume_is_requested_and_repeated_run_is_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            service = self.seed(Path(folder)/"market.sqlite")
            provider = SimpleNamespace(series=Mock(return_value={"2026-01-05": {"volume": 100}}), close=Mock())
            factory = Mock(return_value=provider)
            result = refresh_volumes(service, provider_factory=factory)
            self.assertEqual(result["state"], "complete")
            self.assertEqual(result["saved"], 1)
            provider.series.assert_called_once_with("IF2602.CFE", ["volume"], "2026-01-05", "2026-01-05")
            provider.close.assert_called_once()
            quotes = service.store.quotes("2026-01-02", "2026-01-05")
            self.assertEqual(len(quotes), 32)
            self.assertEqual(quotes[("IF2602.CFE", "2026-01-02", "volume")], 123)
            unused = Mock(side_effect=AssertionError("must not reconnect"))
            second = refresh_volumes(service, provider_factory=unused)
            self.assertEqual(second["requests"], 0)
            unused.assert_not_called()

    def test_zero_volume_is_valid_and_negative_volume_is_not_written(self):
        for value, state in ((0, "complete"), (-1, "partial")):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                service = self.seed(Path(folder)/"market.sqlite")
                provider = SimpleNamespace(series=Mock(return_value={"2026-01-05": {"volume": value}}), close=Mock())
                result = refresh_volumes(service, provider_factory=lambda _: provider)
                self.assertEqual(result["state"], state)
                quotes = service.store.quotes("2026-01-05", "2026-01-05")
                self.assertEqual(("IF2602.CFE", "2026-01-05", "volume") in quotes, value == 0)


if __name__ == "__main__":
    unittest.main()
