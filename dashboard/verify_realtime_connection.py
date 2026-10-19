"""Bounded realtime HTTP collection using the dashboard's existing adapter.

No DDB connection or VPN switching. Keep observations separate from bar history.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import uuid

from dashboard.native.collection import ScopedResolver
from dashboard.native.developer_model import DeveloperModel
from index_strategy.instant_dld.client import MarketDataClient
from index_strategy.instant_dld.collector import collect
from index_strategy.instant_dld.contract_aliases import DualIdentityStore
from index_strategy.instant_dld.service import write_json

ROOT = Path(__file__).resolve().parent
INDICES = ("000300.SH", "000016.SH", "000905.SH", "000852.SH")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--polls", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--refresh-contracts", action="store_true", help="Refresh CFFEX listings and cross-check live identities first")
    args = parser.parse_args()
    if not 1 <= args.polls <= 30:
        parser.error("--polls must be 1–30; use the dashboard UI for continuous collection")
    model = DeveloperModel()
    client = MarketDataClient(connect_timeout=5, read_timeout=10)
    report = {}
    try:
        if args.refresh_contracts:
            report['contract_sync']=model.sync_contract_reference(force=True)
        reference_path = Path(model.config["reference_file"])
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        import pandas as pd
        today = pd.Timestamp.now(tz="Asia/Shanghai").date().isoformat()
        from dashboard.marketdata.contract_reference import active_contracts
        symbols = active_contracts(reference,today)
        symbols = list(dict.fromkeys([*symbols, *INDICES]))
        if len(symbols) <= len(INDICES):
            raise ValueError("Reference data contains no currently listed index futures")
        root = (args.output or Path(model.config.get("realtime_root") or ROOT / "data/realtime_market")).resolve()
        stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S_%f")
        audit = root / "verification" / stamp
        audit.mkdir(parents=True, exist_ok=False)
        symbols_file = audit / "symbols.json"
        write_json(symbols_file, symbols)
        batches = []
        with DualIdentityStore(root) as store:
            original = store.batch
            def batch(record):
                original(record)
                row = {k:record.get(k) for k in ("poll", "status", "http_status", "received_at", "elapsed_seconds", "missing_symbols")}
                row["saved"] = len(store.last_rows)
                batches.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
            store.batch = batch
            summary = collect(client, store, [symbols_file], interval=2, max_polls=args.polls,
                              resolver=ScopedResolver(INDICES, reference_path))
            run_id = store.run_id
        with sqlite3.connect((root / "live/quotes.sqlite3").as_uri()+"?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            count = con.execute("SELECT COUNT(*) FROM quotes WHERE run_id=?", (run_id,)).fetchone()[0]
            latest = [dict(r) for r in con.execute("""SELECT q.symbol,q.source_symbol,q.close,
                q.quote_time,q.received_at,q.trading_date,q.bid_price_1,q.ask_price_1
                FROM quotes q JOIN (SELECT symbol,MAX(sequence) seq FROM quotes WHERE run_id=? GROUP BY symbol) t
                ON q.sequence=t.seq ORDER BY q.symbol""", (run_id,))]
        ok = (len(batches) == args.polls and all(b["status"] == "success" for b in batches)
              and count == len(symbols)*args.polls and all(r["close"] is not None and r["close"] > 0 for r in latest))
        report.update(status="success" if ok else "incomplete", run_id=run_id, realtime_root=str(root),
                      source="existing realtime HTTP MarketDataClient; no DDB", source_date_verified=False,
                      source_time_note="quote_time has time of day only; received_at is collection time, not event time",
                      polls=args.polls, rows=count, instruments=len(latest), batches=batches, quotes=latest,
                      registered=False, historical_roots=model.config["history_roots"])
        # Preserve the completed collection audit even if configuration/publication fails.
        write_json(audit / "report.json", report)
        if args.register and ok:
            backup = audit / "native.before.json"
            write_json(backup, model.config)
            config = deepcopy(model.config)
            if config.get("realtime_root") != str(root) or not config.get("realtime_id"):
                config["realtime_id"] = uuid.uuid4().hex
            config.update(realtime_root=str(root), collection_symbols=symbols)
            model.save_config(config)
            report.update(registered=True, config_backup=str(backup))
            state = model.snapshot(dict(product=config["product"], frequency=config["frequency"], demo=False, save=False))
            report["dashboard"] = dict(live_quotes=state["live_quotes"], book=state["book"],
                book_reason=state["book_reason"], publication_id=state.get("publication_id"),
                publication_error=state.get("publish_error"), indices=state["indices"],
                historical_basis_time=state["basis"].iloc[-1].event_time.isoformat() if len(state["basis"]) else None)
            ok = ok and state["live_quotes"] == len(symbols) and not state.get("publish_error")
        report["status"] = "success" if ok else "incomplete"
        write_json(audit / "report.json", report)
        write_json(root / "verification/latest.json", dict(report=str(audit / "report.json"), status=report["status"]))
        print(json.dumps({k:v for k,v in report.items() if k not in ("quotes", "batches")}, ensure_ascii=False, indent=2), flush=True)
        print("Report: " + str(audit / "report.json"), flush=True)
        return 0 if ok else 2
    finally:
        client.close()
        model.close()


if __name__ == "__main__":
    raise SystemExit(main())
