from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from dashboard.backtest import BacktestConfig, BacktestError, run_backtest
from dashboard.backtest.__main__ import load_job
from dashboard.backtest.calendar_analytics import annual_trade_returns, drawdown_episodes, round_trips
from dashboard.backtest.calendar_study import fingerprints, run_calendar_study, verify_prefixes
from dashboard.backtest.configuration import CTASpec
from dashboard.backtest.strategy import load_factors
from dashboard.backtest.strategy.examples import demo_market
from dashboard.backtest.synthetic import write_inputs
from dashboard.backtest.test.test_data import local_temp
from dashboard.backtest.workflow import cta_stage, factor_stage


def job():
    return dict(data=dict(dividend_mode="ignore"),factor=dict(name="calendar_pair_percentile",roots=["IC"],
        parameters=dict(window_days=3)),cta=dict(name="calendar_reversal",input_factor="calendar_pair_percentile"),
        backtest=dict(start="2026-01-08"))


def fixture():
    market,_=demo_market(35)
    market=replace(market,margin_rate={"IC":.2})
    return market,factor_stage(job(),market_data=market)


class CalendarStudyTests(unittest.TestCase):
    def test_formula_both_channels_and_real_pair_benchmark(self):
        _,factors=fixture()
        table=factors.diagnostics["calendar_pairs"]
        for channel in ("01-03","02-03"):
            row=table.loc[table.channel.eq(channel)&table.history_count.eq(3)&table.percentile.notna()].iloc[5]
            expected=100*(row.near_price-row.far_price)/row.near_price*365/(row.far_t-row.near_t)
            self.assertAlmostEqual(row.annual_spread,expected)
            history=factors.continuous_factors["calendar_pair_annual"].loc[row.history_start:row.history_end,"IC"+channel[:2]+".CFE"]
            self.assertEqual(row.percentile,((history<row.annual_spread).sum()+.5*(history==row.annual_spread).sum())/3)
            self.assertLess(row.history_end,row.timestamp)
        self.assertTrue((~table.is_entry_pair).any())
        verify_prefixes(factors)

    def test_raw_p_strict_open_boundaries(self):
        _,factors=fixture()
        stamp=factors.panel.close.index[4]
        for q,low in ((.8,.2),(.9,.1)):
            for value,expected in ((q,0),(low,0),(q+1e-8,-1),(low-1e-8,1)):
                f=deepcopy(factors)
                f.diagnostics["calendar_pairs"].loc[:,"percentile"]=value
                declaration=job()
                declaration["cta"]["parameters"]=dict(q_open=q)
                declaration["backtest"]=dict(start=str(stamp),end=str(stamp))
                signal=cta_stage(f,declaration)
                count=0 if signal.decisions.empty else signal.decisions.action.eq("signal_open").sum()
                self.assertEqual(count,int(expected!=0))
                if count:
                    self.assertEqual(signal.decisions.direction.iloc[0],expected)

    def test_old_pair_exit_not_new_continuous_pair_and_no_overlap(self):
        _,factors=fixture()
        table=factors.diagnostics["calendar_pairs"]
        table.loc[:,"percentile"]=.5
        first=pd.Timestamp("2026-01-08 15:00",tz="Asia/Shanghai")
        near,far=(factors.panel.mapping.at[first,s] for s in ("IC01.CFE","IC03.CFE"))
        old=table.near.eq(near)&table.far.eq(far)&table.channel.eq("01-03")
        table.loc[old&table.timestamp.ge(first),"percentile"]=.95
        close=pd.Timestamp("2026-01-20 15:00",tz="Asia/Shanghai")
        table.loc[table.is_entry_pair&table.timestamp.ge(close),"percentile"]=.99
        table.loc[old&table.timestamp.eq(close),"percentile"]=.6
        declaration=job()
        declaration["cta"]["parameters"]=dict(exit_mode="threshold",q_close=.6)
        signal=cta_stage(factors,declaration)
        closing=signal.decisions.loc[signal.decisions.action.eq("signal_close")].iloc[0]
        self.assertEqual(closing.timestamp,close)
        self.assertEqual(closing.near,near)
        self.assertNotEqual(near,factors.panel.mapping.at[close,"IC01.CFE"])
        next_open=signal.decisions.loc[signal.decisions.action.eq("signal_open")].iloc[1]
        self.assertGreater(next_open.timestamp,close)

    def test_inclusive_exit_boundaries_for_both_directions(self):
        _,original=fixture()
        dates=original.panel.close.index
        for q_close in (.6,.4):
            for direction in (-1,1):
                factors=deepcopy(original)
                table=factors.diagnostics["calendar_pairs"]
                table.loc[:,"percentile"]=.95 if direction<0 else .05
                boundary=q_close if direction<0 else round(1-q_close,14)
                table.loc[table.timestamp.eq(dates[4]),"percentile"]=boundary+(1e-8 if direction<0 else -1e-8)
                table.loc[table.timestamp.eq(dates[5]),"percentile"]=boundary
                declaration=job()
                declaration["cta"]["parameters"]=dict(exit_mode="threshold",q_close=q_close)
                signals=cta_stage(factors,declaration)
                close=signals.decisions.loc[signals.decisions.action.eq("signal_close")].iloc[0]
                self.assertEqual(close.timestamp,dates[5])
                self.assertEqual(close.direction,direction)

    def test_expiry_wins_over_pending_threshold_without_duplicate_fees(self):
        market,factors=fixture()
        table=factors.diagnostics["calendar_pairs"]
        table.loc[:,"percentile"]=.5
        enter=pd.Timestamp("2026-01-14 15:00",tz="Asia/Shanghai")
        close=pd.Timestamp("2026-02-19 15:00",tz="Asia/Shanghai")
        near,far=(factors.panel.mapping.at[enter,s] for s in ("IC01.CFE","IC03.CFE"))
        selected=table.near.eq(near)&table.far.eq(far)&table.channel.eq("01-03")
        table.loc[selected&table.timestamp.ge(enter)&table.timestamp.lt(close),"percentile"]=.95
        declaration=job()
        declaration["cta"]["parameters"]=dict(exit_mode="threshold",q_close=.6)
        declaration["backtest"]=dict(start="2026-01-13")
        signals=cta_stage(factors,declaration)
        cfg=BacktestConfig(initial_capital=1_000_000,start="2026-01-13",mode="product",weight_mode="neutral_units",
            rebalance_on_change_only=True,preserve_pair_lots=True)
        account=run_backtest(signals.targets,market_data=market,config=cfg).accounts["IC"]
        trip,_,_,stats=round_trips(account,factors,signals,scenario="test",root="IC",channel="01-03",
            initial_capital=cfg.initial_capital,commission_rate=cfg.commission_rate)
        self.assertEqual(len(account.actual_orders),4)
        self.assertEqual(trip.exit_reason.tolist(),["expiry_d0"])
        self.assertEqual(stats["closed_trades"],1)
        self.assertEqual(account.positions.iloc[-1].abs().sum(),0)
        self.assertAlmostEqual(trip.entry_margin.iloc[0],sum(account.actual_orders.iloc[:2].notional*.2))

    def test_pending_close_waits_for_saved_quote_and_never_reads_market(self):
        _,factors=fixture()
        table=factors.diagnostics["calendar_pairs"]
        table.loc[:,"percentile"]=.95
        dates=factors.panel.close.index
        table.loc[table.timestamp.eq(dates[4]),"percentile"]=.5
        table.loc[table.timestamp.eq(dates[5]),"quote_valid"]=False
        declaration=job()
        declaration["cta"]["parameters"]=dict(exit_mode="threshold")
        with patch("dashboard.backtest.strategy.pipeline._load_market",side_effect=AssertionError("CTA must not read market")):
            signals=cta_stage(factors,declaration)
        opens=signals.decisions.loc[signals.decisions.action.eq("signal_open")]
        self.assertEqual(opens.timestamp.iloc[1],dates[6])

    def test_saved_factor_unchanged_across_all_cta_rules(self):
        _,factors=fixture()
        before=fingerprints(factors)
        with local_temp() as root:
            factors.save(root/"factor")
            for channel in ("01-03","02-03"):
                for q in (.8,.9):
                    for mode,close in (("expiry",.6),("threshold",.6),("threshold",.4)):
                        declaration=job()
                        declaration["cta"]["parameters"]=dict(channel=channel,q_open=q,exit_mode=mode,q_close=close)
                        a=cta_stage(factors,declaration)
                        b=cta_stage(load_factors(root/"factor"),declaration)
                        pd.testing.assert_frame_equal(a.targets,b.targets)
            self.assertEqual(before,fingerprints(factors))

    def test_drawdown_top_three_nonoverlap_with_initial_anchor_and_unrecovered(self):
        curve=pd.Series([99,110,99,110,111,90,112,100,108],index=pd.date_range("2026-01-01",periods=9))
        episodes,detail=drawdown_episodes(curve,100,scenario="test")
        self.assertEqual(len(episodes),3)
        self.assertEqual(episodes.iloc[0].trough_date,curve.index[5])
        self.assertEqual(episodes.iloc[0].recovery_date,curve.index[6])
        self.assertFalse(episodes.iloc[1].recovered)
        self.assertAlmostEqual(episodes.iloc[0].drawdown,90/111-1)
        self.assertAlmostEqual(detail.drawdown.min(),episodes.iloc[0].drawdown)

    def test_annualization_not_applicable_is_not_clipped(self):
        self.assertEqual(annual_trade_returns(-120,100,10)[0],-1.2)
        self.assertTrue(np.isnan(annual_trade_returns(-120,100,10)[1]))
        self.assertEqual(annual_trade_returns(10,100,0)[3],"holding_days_zero")
        ratio,amount,annual,status=annual_trade_returns(10,100,365)
        self.assertEqual((ratio,amount,status),(.1,10.,"applicable"))
        self.assertAlmostEqual(annual,.1)
        with self.assertRaises(BacktestError):
            CTASpec(name="calendar_reversal",parameters=dict(q_open=.5))

    def test_full_48_matrix_with_standalone_reruns(self):
        with local_temp() as root:
            declaration=load_job(write_inputs(root/"inputs")/"structure.local.json")
            declaration["factor"].update(name="calendar_pair_percentile",parameters=dict(window_days=3))
            declaration["data"]["margin_rates"]={r:.2 for r in ("IF","IH","IC","IM")}
            declaration["cta"]=dict(name="calendar_reversal",input_factor="calendar_pair_percentile")
            declaration["backtest"].update(initial_capital=1_000_000,start="2026-01-08",preserve_pair_lots=True,workers=1)
            result=run_calendar_study(declaration,root/"study",render=False,progress=lambda _:None)
            self.assertEqual(len(result["metrics"]),48)
            self.assertEqual(result["protocol"]["standalone_verified"],48)
            summary=result["metrics"]
            self.assertTrue((summary.winning_trades+summary.losing_trades+summary.flat_trades).eq(summary.closed_trades).all())
            pd.testing.assert_series_equal(summary.net_pnl,summary.closed_net_pnl+summary.open_net_pnl,check_names=False,atol=1e-5)


if __name__=="__main__":
    unittest.main()
