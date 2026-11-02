from dataclasses import replace
import unittest

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestConfig, BacktestError, MarketData, run_backtest
from dashboard.backtest.analytics import performance_metrics
from dashboard.backtest.configuration import CTASpec, FactorSpec
from dashboard.backtest.pair_analytics import attribute_calendar_pairs, attribute_index_pairs
from dashboard.backtest.strategy import ContinuousPanel, load_factors
from dashboard.backtest.strategy.annual_calendar import annual_calendar_spread
from dashboard.backtest.strategy.examples import demo_market
from dashboard.backtest.strategy.term_structure import conditional_rank, fit_quantiles, quantile_key
from dashboard.backtest.test.test_data import local_temp
from dashboard.backtest.workflow import cta_stage, factor_stage


def regression_job(roots=("IC",), workers=1):
    return dict(data=dict(dividend_mode="ignore"), factor=dict(name="term_structure_percentile",roots=roots,workers=workers,
        parameters=dict(window_days=3,min_training_samples=8,quantiles=(.1,.5,.9),degree=1,min_annual_days=5)))


class TermStructureTests(unittest.TestCase):
    def test_calendar_annualization_uses_difference_of_remaining_natural_days(self):
        index=pd.date_range("2026-01-05 15:00",periods=3,tz="Asia/Shanghai")
        columns=["IC01.CFE","IC03.CFE"]
        close=pd.DataFrame([[100,103]]*3,index=index,columns=columns,dtype=float)
        days=pd.DataFrame([[30,120],[29,119],[28,118]],index=index,columns=columns,dtype=float)
        panel=ContinuousPanel(close,close*0+98,close*0,days,close.astype(object))
        annual,_=annual_calendar_spread(panel)
        np.testing.assert_allclose(annual["IC01.CFE"], -3/100*36500/90)
        spot,_=annual_calendar_spread(panel,price_base="spot")
        self.assertAlmostEqual(spot.iloc[0,0], -3/98*36500/90)
        panel.dividend_points.iloc[1,1]=np.nan
        missing,_=annual_calendar_spread(panel)
        self.assertTrue(np.isnan(missing.iloc[1,0]))
        panel.days_to_expiry.iloc[0,1]=30
        with self.assertRaisesRegex(BacktestError,"positive far-minus-near"):
            annual_calendar_spread(panel)

    def test_quantile_lp_matches_exact_pinball_objective_and_free_negative_intercept(self):
        y=np.arange(10,dtype=float)
        probs=(.1,.5,.9)
        betas,objective=fit_quantiles(np.ones((10,1)),y,probs)
        for beta,value,q in zip(betas,objective,probs):
            def loss(prediction):
                residual=y-prediction
                return np.maximum(q*residual,(q-1)*residual).sum()
            self.assertAlmostEqual(value,min(loss(candidate) for candidate in y))
            self.assertAlmostEqual(loss(beta[0]),value)
        x=np.column_stack([np.ones(10),np.arange(10)])
        beta,losses=fit_quantiles(x,-5+2*np.arange(10),probs)
        np.testing.assert_allclose(beta,[[-5,2]]*3,atol=1e-7)
        np.testing.assert_allclose(losses,0,atol=1e-7)

    def test_crossed_quantiles_are_rearranged_and_ties_have_mean_rank(self):
        rank,ordered=conditional_rank(2,[3,2,1],[.1,.5,.9])
        self.assertEqual(rank,.5)
        self.assertEqual(quantile_key(.5),"term_structure_q500")
        self.assertEqual(len({quantile_key(q) for q in (.4996,.5,.5004)}),3)
        np.testing.assert_equal(ordered,[1,2,3])
        rank,_=conditional_rank(2,[2,2,2],[.1,.5,.9])
        self.assertEqual(rank,.5)

    def test_regression_prefix_replay_and_current_day_does_not_enter_fitted_curves(self):
        market,_=demo_market(periods=25)
        job=regression_job()
        full=factor_stage(job,market_data=market)
        replay=factor_stage(job,market_data=replace(market,close=market.close.iloc[:18]))
        for name in full.continuous_factors:
            pd.testing.assert_frame_equal(full.continuous_factors[name].iloc[:18],replay.continuous_factors[name])
        changed=market.close.copy()
        changed.iloc[-1,changed.columns.get_loc("IC_spot")]*=1.5
        altered=factor_stage(job,market_data=replace(market,close=changed))
        for name in full.continuous_factors:
            if name.startswith("term_structure_q"):
                pd.testing.assert_frame_equal(full.continuous_factors[name],altered.continuous_factors[name])
        audit=full.diagnostics["quantile_models"]
        fitted=audit.loc[audit.status.eq("fit")]
        self.assertGreater(len(fitted),0)
        self.assertTrue((fitted.train_end.dt.normalize()<fitted.timestamp.dt.normalize()).all())

    def test_saved_regression_model_and_diagnostics_round_trip(self):
        market,_=demo_market(periods=15)
        with local_temp() as root:
            result=factor_stage(regression_job(),market_data=market,output_dir=root/"factor")
            saved=load_factors(root/"factor")
            pd.testing.assert_frame_equal(result.diagnostics["quantile_models"],saved.diagnostics["quantile_models"],check_freq=False)
            pd.testing.assert_frame_equal(result.continuous_factors["term_structure_percentile"],saved.continuous_factors["term_structure_percentile"],check_freq=False)

    def test_serial_and_parallel_conditional_quantiles_match(self):
        market,_=demo_market(periods=15)
        frames,contracts=[],{}
        for root in ("IC","IF"):
            frames.append(market.close.rename(columns={s:root+s[2:] for s in market.close}))
            contracts.update({root+s[2:]:dict(ref,instrument_id=root+s[2:]) for s,ref in market.contracts.items()})
        shared=MarketData(pd.concat(frames,axis=1),contracts=contracts)
        one=factor_stage(regression_job(("IC","IF"),1),market_data=shared)
        two=factor_stage(regression_job(("IC","IF"),2),market_data=shared)
        for name in one.continuous_factors:
            pd.testing.assert_frame_equal(one.continuous_factors[name],two.continuous_factors[name])

    def test_another_pair_entry_does_not_resize_existing_pair(self):
        dates=pd.date_range("2026-09-21",periods=5)
        a,b="IC2612.CFE","IC2703.CFE"
        market=MarketData(pd.DataFrame({a:[100,100,200,210,220],b:100.,"IC_spot":100.},index=dates),
            margin_rate={"IC":1},contracts={a:dict(expiry_date="2026-09-25"),b:dict(expiry_date="2027-03-19")})
        targets=pd.DataFrame({a:[.12,.12,.12],b:[0,.12,0],"IC_spot":[-.12,-.24,-.12]},index=dates[[0,1,3]])
        cfg=BacktestConfig(initial_capital=1_000_000,weight_mode="neutral_units",mode="product",preserve_pair_lots=True)
        held=run_backtest(targets,market_data=market,config=cfg).accounts["IC"]
        ordinary=run_backtest(targets,market_data=market,config=replace(cfg,preserve_pair_lots=False)).accounts["IC"]
        self.assertEqual(held.positions[a].iloc[1:4].tolist(),[6,6,6])
        self.assertNotEqual(ordinary.positions[a].iloc[2],6)
        changes=held.actual_orders.loc[held.actual_orders.symbol.eq(a)]
        self.assertEqual(changes.quantity.tolist(),[6,6])
        detail,summary=attribute_index_pairs(held,market,initial_capital=1_000_000)
        self.assertAlmostEqual(summary.net_pnl.sum(),held.equity.equity.iloc[-1]-1_000_000)
        self.assertTrue((detail.future_lots*detail.multiplier+detail.hedge_units).eq(0).all())

    def test_netted_index_pairs_do_not_charge_fictitious_gross_index_fees(self):
        a,b="IC2612.CFE","IC2703.CFE"
        market=MarketData(pd.DataFrame({a:[100,100,110],b:[100,100,105],"IC_spot":[100,100,120]},index=pd.date_range("2026-09-21",periods=3)),margin_rate={"IC":1})
        targets=pd.DataFrame({a:[.1],b:[-.1],"IC_spot":[0.]},index=["2026-09-21"])
        result=run_backtest(targets,market_data=market,config=BacktestConfig(initial_capital=1_000_000,weight_mode="neutral_units",mode="product",d0=None)).accounts["IC"]
        detail,summary=attribute_index_pairs(result,market,initial_capital=1_000_000)
        self.assertFalse(result.actual_orders.symbol.eq("IC_spot").any())
        self.assertAlmostEqual(summary.net_pnl.sum(),4940)
        self.assertAlmostEqual(summary.fees_cumulative.sum(),60)
        self.assertAlmostEqual(summary.hedge_pnl.sum(),0)
        self.assertAlmostEqual(summary.allocated_actual_margin.sum(),215000)
        self.assertAlmostEqual(summary.gross_pair_margin.sum(),455000)
        self.assertGreater(len(detail),0)

    def test_calendar_pair_attribution_reconstructs_both_actual_legs(self):
        a,b="IC2612.CFE","IC2703.CFE"
        market=MarketData(pd.DataFrame({a:[100,100,110],b:[101,101,105]},index=pd.date_range("2026-09-21",periods=3)),
            margin_rate={"IC":1},contracts={a:dict(expiry_date="2026-09-23"),b:dict(expiry_date="2027-03-19")})
        targets=pd.DataFrame({a:[.495],b:[-.495]},index=["2026-09-21"])
        account=run_backtest(targets,market_data=market,config=BacktestConfig(initial_capital=100000,weight_mode="neutral_units")).accounts["portfolio"]
        detail,summary=attribute_calendar_pairs(account,market,initial_capital=100000)
        self.assertAlmostEqual(summary.net_pnl.sum(),account.equity.equity.iloc[-1]-100000)
        self.assertTrue((detail.future_lots+detail.hedge_units).eq(0).all())
        self.assertEqual(summary.future_lots.iloc[0],0)

    def test_calendar_cagr_uses_actual_elapsed_days(self):
        curve=pd.Series([100,120,110,121],index=pd.to_datetime(["2025-01-01","2025-05-01","2025-08-01","2027-01-01"]))
        metrics=performance_metrics(curve,100)
        self.assertAlmostEqual(metrics["total_return"],.21)
        self.assertAlmostEqual(metrics["annualized_return"],.1)
        self.assertEqual(metrics["elapsed_calendar_days"],730)
        self.assertAlmostEqual(metrics["max_drawdown"],110/120-1)
        self.assertIsNone(performance_metrics(curve.iloc[:1],100)["annualized_return"])

    def test_structure_cta_requires_shared_product_account_and_pair_lot_preservation(self):
        market,_=demo_market(periods=15)
        job=dict(data=dict(dividend_mode="ignore"),factor=dict(name="basis_percentile",parameters=dict(window_days=3)),
                 cta=dict(name="expiry_index_structure",input_factor="basis_percentile"))
        result=cta_stage(factor_stage(job,market_data=market),job)
        required=result.metadata["required_backtest_options"]
        self.assertEqual(required["mode"],"product")
        self.assertTrue(required["preserve_pair_lots"])
        self.assertTrue(np.allclose(result.targets.sum(axis=1),0))
        self.assertEqual(CTASpec(name="expiry_index_structure").parameters["position_weight"],.12375)
        with self.assertRaises(BacktestError):
            FactorSpec(name="term_structure_percentile",parameters=dict(min_training_samples=10000))
        with self.assertRaises(BacktestError):
            FactorSpec(name="annual_calendar_spread",slots=(0,2))


if __name__ == "__main__":
    unittest.main()
