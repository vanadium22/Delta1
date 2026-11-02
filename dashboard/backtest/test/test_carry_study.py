from dataclasses import replace
import json
import unittest

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestConfig, BacktestError, DataConfig, MarketData, audit_data, load_market_data, load_result
from dashboard.backtest.data_events import load_event_market_data
from dashboard.backtest.acquire_daily import acquire_daily, audit_daily, clean_prices, reference_rows
from dashboard.backtest.carry_study import CarryStudyConfig, run_carry_study
from dashboard.backtest.strategy.examples import demo_market
from dashboard.backtest.test.test_data import local_temp


def four_product_market():
    seed, _ = demo_market(28)
    close, contracts = pd.DataFrame(index=seed.close.index), {}
    for root in ("IF", "IH", "IC", "IM"):
        for symbol in seed.close:
            close[root+symbol[2:]] = seed.close[symbol]
        for symbol, ref in seed.contracts.items():
            contracts[root+symbol[2:]] = {**ref, "instrument_id":root+symbol[2:]}
    return MarketData(close, {"IF":300,"IH":300,"IC":200,"IM":200}, {r:.15 for r in ("IF","IH","IC","IM")},
                      contracts=contracts, metadata=dict(source="isolated_synthetic_test"))


class FakeSession:
    def __init__(self, market):
        self.values = {}
        self.reference = pd.DataFrame([dict(S_INFO_WINDCODE=s, S_INFO_LISTDATE=pd.Timestamp(r["listing_date"]),
            S_INFO_DELISTDATE=pd.Timestamp(r["expiry_date"]), OPDATE=pd.Timestamp("2025-01-01")) for s,r in market.contracts.items()])
        raw = market.close.rename(columns={"IF_spot":"000300.SH","IH_spot":"000016.SH","IC_spot":"000905.SH","IM_spot":"000852.SH"})
        self.prices = raw.reset_index(names="trade_date").melt(id_vars="trade_date", var_name="symbol", value_name="close").dropna()
        self.prices["trade_date"] = self.prices.trade_date.dt.tz_localize(None).dt.normalize()

    def upload(self, values):
        self.values.update(values)

    def run(self, query):
        if "cfuturesdescription" in query:
            frame = self.reference
        else:
            frame = self.prices.loc[self.prices.symbol.isin(self.values["btSymbols"])
                & self.prices.trade_date.between(pd.Timestamp(self.values["btLeft"]), pd.Timestamp(self.values["btRight"]))]
        return len(frame) if query.startswith("exec count") else frame.copy()


class FakeClient:
    def __init__(self, market):
        self.session, self.config, self.closed = FakeSession(market), {}, False

    def close(self):
        self.closed = True


class CarryStudyTests(unittest.TestCase):
    def test_four_products_both_thresholds_and_independent_contracts_reconcile(self):
        market = four_product_market()
        config = CarryStudyConfig(start="2026-01-12", end="2026-02-11", window_days=3, workers=1, initial_capital=100_000)
        with local_temp() as root:
            result = run_carry_study(market_data=market, config=config, output_dir=root / "study", render=False)
            summary = result["summary"]
            self.assertEqual(len(summary.query("scope == 'product_best'")), 8)
            self.assertEqual(set(summary.root), {"IF", "IH", "IC", "IM"})
            self.assertGreater(len(summary.query("scope == 'contract_independent'")), 8)
            np.testing.assert_allclose(summary.net_pnl, summary.futures_pnl+summary.spot_pnl, atol=1e-7)
            self.assertTrue(result["metadata"]["requested_period_verified"])
            self.assertGreater(len(result["trades"]), 0)
            for row in result["trades"].itertuples():
                multiple = market.multiplier[row.root]
                self.assertEqual(row.spot_signed_units, -multiple*row.futures_signed_lots)
                self.assertGreater(row.entry_time, row.signal_time)
            self.assertTrue((root / "study/factor_values.csv").is_file())
            self.assertTrue((root / "study/product_best_0_9/job.local.json").is_file())

    def test_incomplete_requested_history_is_not_reported_as_full_backtest(self):
        market = four_product_market()
        with local_temp() as root:
            with self.assertRaisesRegex(BacktestError, "coverage is incomplete"):
                run_carry_study(market_data=market, output_dir=root / "strict", render=False)
            state = json.loads((root / "strict/status.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "data_incomplete")

    def test_one_shot_daily_acquisition_is_read_only_bounded_and_preserves_manifest(self):
        market = four_product_market()
        market = replace(market, close=market.close.iloc[:5])
        client = FakeClient(market)
        with local_temp() as root:
            result = acquire_daily(root / "local.connection.json", root / "download", start="2026-01-05", end="2026-01-09",
                                   client_factory=lambda _:client)
            self.assertTrue(client.closed)
            self.assertEqual(result["coverage"]["status"], "complete")
            self.assertFalse(result["vpn_operation"])
            self.assertTrue((root / "download/daily_close.parquet").is_file())
            self.assertTrue((root / "download/reference.json").is_file())
            self.assertTrue((root / "download/data_config.local.json").is_file())
            self.assertTrue((root / "下载索引.md").is_file())

    def test_price_conflicts_missing_values_and_reference_conflicts_are_explicit(self):
        frame = pd.DataFrame(dict(symbol=["IC2612.CFE"]*2, trade_date=["2026-01-05"]*2, close=[100,101]))
        with self.assertRaisesRegex(BacktestError, "Conflicting daily"):
            clean_prices(frame, ["IC2612.CFE"])
        frame = frame.iloc[:1].copy()
        frame["close"] = 0
        with self.assertRaisesRegex(BacktestError, "nonpositive"):
            clean_prices(frame, ["IC2612.CFE"])
        refs = FakeSession(four_product_market()).reference.iloc[:1]
        changed = refs.copy()
        changed["S_INFO_DELISTDATE"] += pd.Timedelta(days=1)
        with self.assertRaisesRegex(BacktestError, "conflict"):
            reference_rows(pd.concat([refs,changed]), "2026-11-02T00:00:00Z")

    def test_coverage_audit_detects_internal_missing_index_day(self):
        market = four_product_market()
        close = market.close.iloc[:5].copy()
        close.iloc[1,close.columns.get_loc("IF_spot")] = np.nan
        audit = audit_daily(close, market.contracts, "2026-01-05", "2026-01-09")
        self.assertEqual(audit["status"], "incomplete")
        self.assertIn("IF_spot", audit["interior_gaps"][0]["missing"])

    def test_mixed_z_lineage_is_blocked_before_loading_cached_price_parts(self):
        from dashboard.marketdata.bars import BarDataset
        with local_temp() as root:
            store = BarDataset.create(root / "mixed", dict(dataset_id="excluded_mixed", source_id="local_ddb_plus_readonly_z_v1",
                series_kind="concrete", price_adjustment="none", volume_unit="unused", availability_policy="verified",
                instruments={"IC2612.CFE":dict(asset_type="cn_index_future",market_region="CN")}))
            data = DataConfig(history_roots=(store.root,))
            with self.assertRaisesRegex(BacktestError, "Z-derived"):
                load_market_data(data)
            with self.assertRaisesRegex(BacktestError, "Z-derived"):
                audit_data(data)
            targets = pd.DataFrame({"IC2612.CFE":[.5]}, index=pd.DatetimeIndex(["2026-09-21 15:00"],tz="Asia/Shanghai"))
            with self.assertRaisesRegex(BacktestError, "Z-derived"):
                load_event_market_data(data, targets, BacktestConfig())
            mixed = replace(four_product_market(), metadata=dict(source_id="local_ddb_plus_readonly_z_v1"))
            with self.assertRaisesRegex(BacktestError, "Z-derived"):
                run_carry_study(market_data=mixed, output_dir=root / "rejected", render=False)
            self.assertFalse((root / "rejected/factor_values.parquet").exists())
            (root / "old_result").mkdir()
            (root / "old_result/metadata.json").write_text(json.dumps(dict(market_data=mixed.metadata)), encoding="utf-8")
            with self.assertRaisesRegex(BacktestError, "Z-derived"):
                load_result(root / "old_result")


if __name__ == "__main__":
    unittest.main()
