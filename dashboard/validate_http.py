"""Bounded company HTTP probe. Never imports any DDB client or VPN helper."""
import json
from pathlib import Path
import time
from index_strategy.instant_dld.client import MarketDataClient
from index_strategy.instant_dld.realtime_store import RealtimeStore
from dashboard.marketdata.paths import REALTIME_ROOT, VALIDATION_ROOT

def main():
    config = json.loads((Path(__file__).parent / "localsetting/native.json").read_text(encoding="utf-8"))
    client = MarketDataClient(connect_timeout=5, read_timeout=10)
    reports = []
    try:
        with RealtimeStore(REALTIME_ROOT) as store:
            store.interval_seconds = 2
            for poll in range(1, 4):
                record = client.fetch(config["collection_symbols"])
                record.update(poll=poll, batch=1, batch_count=1)
                store.batch(record)
                reports.append({k:record.get(k) for k in ("status", "http_status", "received_at", "elapsed_seconds", "missing_symbols", "error")})
                reports[-1]["quotes"] = [{k:r.get(k) for k in ("symbol", "close", "prev_close", "open", "high", "low", "volume_total", "volume", "open_interest_raw", "open_interest", "oi_reason", "quote_time", "source_event_time", "date_status", "snapshot_status", "is_final", "bid_price_1", "ask_price_1", "bid_price_2", "pre_settlement_raw")} for r in store.last_rows]
                if poll < 3: time.sleep(2)
    finally: client.close()
    VALIDATION_ROOT.mkdir(parents=True, exist_ok=True)
    (VALIDATION_ROOT/"http_probe.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{"status":r["status"], "received_at":r["received_at"], "quotes":len(r["quotes"]), "zero_oi":sum(q["open_interest_raw"] == 0 for q in r["quotes"])} for r in reports],ensure_ascii=False))

if __name__ == "__main__": main()
