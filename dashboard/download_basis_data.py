"""Explicit, read-only DDB downloads through the shared project data interface.

Run from the Delta1 project root. No connection credentials live in this project.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SHARED = ROOT.parents[2] / "project/market_data/examples"
PRODUCTS = ("IF", "IH", "IC", "IM")
INDICES = ("000300.SH", "000016.SH", "000905.SH", "000852.SH")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--months", nargs="+", default=["2610", "2611", "2612", "2703"])
    parser.add_argument("--frequency", choices=["1d", "1m"], default="1d")
    from dashboard.marketdata.paths import DATA_ROOT
    parser.add_argument("--output", type=Path, default=DATA_ROOT / "market/index_futures/dashboard/downloads")
    parser.add_argument("--download", action="store_true", help="Explicitly save market data; otherwise preview")
    args = parser.parse_args()
    sys.path.insert(0, str(SHARED))
    from history_client import run_history_worker

    symbols = [p + month + ".CFE" for p in PRODUCTS for month in args.months] + list(INDICES)
    request = dict(symbols=symbols, start=args.start, end=args.end,
                   frequency=args.frequency, fields=["open", "high", "low", "close", "volume", "amount"],
                   oi=True, depth=0, mode="fill" if args.frequency == "1d" else "native",
                   derive_source="1m" if args.frequency == "1d" else "auto",
                   action="download" if args.download else "preview", output_dir=str(args.output.resolve()))
    def progress(event):
        if event.get("type") in {"progress", "error", "log"}:
            print(json.dumps(event, ensure_ascii=False), flush=True)
    result = run_history_worker(request, on_event=progress)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if result["exit_code"] == 0 and result["state"] in {"complete", "preview"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
