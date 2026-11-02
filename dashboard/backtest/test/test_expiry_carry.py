from dataclasses import replace
import unittest

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestConfig, MarketData, index_hedges, run_backtest
from dashboard.backtest.analytics import attribute_legs
from dashboard.backtest.calendar import verified_days
from dashboard.backtest.strategy import hold_to_expiry_targets


def carry_inputs():
    index = pd.date_range("2026-09-21 15:00", periods=5, freq="B", tz="Asia/Shanghai")
    contracts = {"IC2612.CFE": dict(listing_date="2026-01-01", expiry_date="2026-09-23"),
                 "IC2703.CFE": dict(listing_date="2026-01-01", expiry_date="2027-03-19")}
    mapping = pd.DataFrame({"IC00.CFE": "IC2612.CFE", "IC01.CFE": "IC2703.CFE"}, index=index)
    p = pd.DataFrame({"IC2612.CFE": [.99, .1, .99, np.nan, np.nan], "IC2703.CFE": [.97, .99, .98, .1, .99]}, index=index)
    return p, mapping, contracts


class ExpiryCarryTests(unittest.TestCase):
    def test_product_selects_absolute_extreme_reverses_and_ignores_mid_hold_signal(self):
        p, mapping, contracts = carry_inputs()
        result = hold_to_expiry_targets(p, mapping, contracts, start="2026-09-21", threshold=.9, roots=("IC",))
        opens = result.decisions.query("action == 'signal_open'")
        self.assertEqual(opens.symbol.tolist(), ["IC2612.CFE", "IC2703.CFE"])
        self.assertEqual(opens.timestamp.tolist(), [p.index[0], p.index[2]])
        self.assertEqual(result.targets.loc[p.index[0], "IC2612.CFE"], -.99)
        self.assertEqual(result.targets.loc[p.index[2]].tolist(), [0, -.99])
        self.assertNotIn(p.index[1], result.targets.index)

    def test_low_percentile_opens_long_and_two_thresholds_are_distinct(self):
        p, mapping, contracts = carry_inputs()
        p.iloc[0] = [.06, .8]
        high = hold_to_expiry_targets(p, mapping, contracts, start="2026-09-21", threshold=.9, roots=("IC",))
        low = hold_to_expiry_targets(p, mapping, contracts, start="2026-09-21", threshold=.8, roots=("IC",))
        self.assertTrue(high.targets.iloc[0].eq(0).all())
        self.assertEqual(low.targets.loc[p.index[0], "IC2612.CFE"], .99)

    def test_independent_accounts_do_not_compete_and_prefix_targets_are_stable(self):
        p, mapping, contracts = carry_inputs()
        full = hold_to_expiry_targets(p, mapping, contracts, start="2026-09-21", threshold=.9,
                                      roots=("IC",), selection="contract_independent")
        self.assertEqual(full.targets.loc[p.index[0]].tolist(), [-.99, -.99])
        short = hold_to_expiry_targets(p.iloc[:2], mapping.iloc[:2], contracts, start="2026-09-21", threshold=.9,
                                       roots=("IC",), selection="contract_independent")
        pd.testing.assert_frame_equal(full.targets.loc[full.targets.index <= p.index[1]], short.targets)

    def test_attribution_with_expiry_and_entry_rounds_reconciles_exactly(self):
        p, mapping, contracts = carry_inputs()
        signals = hold_to_expiry_targets(p, mapping, contracts, start="2026-09-21", threshold=.9, roots=("IC",))
        close = pd.DataFrame({"IC2612.CFE": [100, 100, 103, np.nan, np.nan],
                              "IC2703.CFE": [101, 100, 104, 105, 106], "IC_spot": [100, 100, 102, 103, 104]}, index=p.index)
        market = MarketData(close, {"IC": 200}, {"IC": .1}, contracts=contracts)
        config = BacktestConfig(initial_capital=100_000, hedges=index_hedges(list(contracts)), mode="product", rebalance_on_change_only=True)
        result = run_backtest(signals.targets, market_data=market, config=config)
        account = result.accounts["IC"]
        attributed, legs = attribute_legs(account, market, initial_capital=100_000)
        np.testing.assert_allclose(attributed.net_pnl, account.equity.equity - 100_000, atol=1e-8)
        np.testing.assert_allclose(legs.sum(axis=1), attributed.net_pnl, atol=1e-8)
        self.assertEqual(account.actual_orders.query("reason == 'expiry_d0'").symbol.tolist(), ["IC2612.CFE", "IC_spot"])
        serial = run_backtest(signals.targets, market_data=market, config=replace(config, mode="contract_pair", workers=1))
        self.assertEqual(len(serial.accounts), 2)

    def test_verified_calendar_excludes_holidays_and_includes_first_2024_session(self):
        self.assertEqual(verified_days("2024-01-01", "2024-01-03"), ["2024-01-02", "2024-01-03"])
        self.assertEqual(verified_days("2024-02-09", "2024-02-19"), ["2024-02-19"])
        self.assertEqual(verified_days("2023-09-29", "2023-10-09"), ["2023-10-09"])


if __name__ == "__main__":
    unittest.main()
