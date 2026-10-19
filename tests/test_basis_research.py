import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from dashboard.native.pair_research import (align, build_research, export_research, history_stats, MULTIPLIERS)
from dashboard.marketdata.ddb_import import convert_file, import_runs


def prices(values, frequency="1d"):
    times = pd.bdate_range("2026-06-01", periods=len(values), tz="Asia/Shanghai") + pd.Timedelta(hours=15) if frequency == "1d" else pd.date_range("2026-10-09 13:01", periods=len(values), freq="min", tz="Asia/Shanghai")
    return pd.DataFrame(dict(event_time=times.tz_convert("UTC"), trade_date=times.date, session_id="day" if frequency == "1d" else "pm", close=values))


def states():
    n = 75
    t = np.arange(n)
    rb = .001*np.sin(t*.9)+.0005*np.cos(t*.37)
    sa = 4200*np.exp(np.cumsum(1.3*rb + .0001*np.sin(t*2.2)))
    sb = 6000*np.exp(np.cumsum(rb))
    result = {}
    for product, spot in (("IF",sa),("IC",sb)):
        frames = {}
        metadata = {}
        for month, offset, expiry in (("2610",-.004,"2026-10-16"),("2612",-.009,"2026-12-18")):
            symbol = product+month+".CFE"
            variation = .0005*np.sin(t*.41 + (0 if product=="IF" else 1.2))
            frames[symbol] = prices(spot*np.exp(offset+variation))
            metadata[symbol] = {"expiry_date":expiry}
        result[product] = dict(product=product,frequency="1d",spot=prices(spot),
            roles={"$spot":"000300.SH" if product=="IF" else "000905.SH"},
            contract_frames=frames,contract_metadata=metadata)
    return result


class PairResearchTests(unittest.TestCase):
    def test_alignment_rejects_stale_or_invalid_latest(self):
        a = prices([1.,2.,3.])
        self.assertFalse(align({"a":a,"b":a.iloc[:-1]})[1])
        b=a.copy();b.loc[2,"close"]=np.nan
        self.assertFalse(align({"a":a,"b":b})[1])
        duplicate = pd.concat([a,a.tail(1)])
        self.assertFalse(align({"a":a,"b":duplicate})[1])

    def test_z_excludes_current(self):
        frame=prices(np.arange(1.,22.));frame["value"]=np.arange(21.)
        frame.loc[20,"value"]=100.
        result=history_stats(frame,"value","1d")
        self.assertAlmostEqual(result["z"],(100-9.5)/np.std(np.arange(20.),ddof=1))
        self.assertEqual(result["percentile"],100)

    def test_intraday_gaps_and_sessions_invalidate_statistics(self):
        frame=prices(np.arange(1.,23.),"1m");frame["value"]=np.arange(22.)
        frame=frame.drop(index=10)
        self.assertIsNone(history_stats(frame,"value","1m")["z"])
        frame=prices(np.arange(1.,22.),"1m");frame["value"]=np.arange(21.)
        frame.loc[0,"session_id"]="am"
        self.assertIsNone(history_stats(frame,"value","1m")["z"])

    def test_cross_decomposition_and_multiplier_hedge(self):
        data=states();research=build_research(data)
        self.assertEqual(len(research["basis"]),4)
        self.assertEqual(len(research["calendar"]),2)
        self.assertEqual(len(research["cross"]),2)
        for row in research["cross"]:
            self.assertAlmostEqual(row["futures_change5"],row["spot_change5"]+row["basis_change5"],places=8)
            self.assertAlmostEqual(row["weighted_futures_change5"],row["weighted_spot_change5"]+row["weighted_basis_change5"],places=8)
            fa=data["IF"]["contract_frames"][row["left"]].iloc[-1].close
            fb=data["IC"]["contract_frames"][row["right"]].iloc[-1].close
            self.assertAlmostEqual(row["hedge_contracts"],row["beta"]*fa*300/(fb*200))

    def test_beta_excludes_current_and_uses_indices(self):
        data=states();before=build_research(data)["cross"][0]["beta"]
        data["IF"]["spot"].loc[74,"close"]*=1.4
        for frame in data["IF"]["contract_frames"].values():frame.loc[74,"close"]*=1.4
        after=build_research(data)["cross"][0]["beta"]
        self.assertAlmostEqual(before,after)

    def test_expiry_uses_observation_day_and_hides_short_annualization(self):
        data=states();row=build_research(data)["basis"][0]
        day=data["IF"]["spot"].iloc[-1].trade_date
        self.assertEqual(row["dte"],(pd.Timestamp("2026-10-16").date()-day).days)
        for product in data.values():
            for meta in product["contract_metadata"].values():meta["expiry_date"]=(pd.Timestamp(day)+pd.Timedelta(days=4)).date().isoformat()
        self.assertTrue(all(r["annual_pct"] is None for r in build_research(data)["basis"]))

    def test_export_strips_private_state_and_has_finite_json(self):
        research=build_research(states());research["private_path"]="secret"
        research["basis"][0]["raw_config"]={"credential":"secret"}
        text=json.dumps(export_research(research),allow_nan=False)
        self.assertNotIn("secret",text)

    def test_import_refuses_batch_with_no_valid_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"run.json"
            path.write_text(json.dumps(dict(version=2,state="partial",errors=[],files=[],skipped=[
                dict(symbol="IF2610.CFE",source_symbol="IF2610.CFE",date="2026-10-09",status="unavailable")])) ,encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"没有可导入的有效数据"):
                import_runs([path],Path(folder)/"normalized")


if __name__ == "__main__":unittest.main()
