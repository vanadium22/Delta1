"""Read contract dates using the shared DDB Client and its VPN lifecycle."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    args = parser.parse_args()
    import re
    if not all(re.fullmatch(r"(?:IF|IH|IC|IM)\d{4}\.CFE", s) for s in args.symbols):
        raise ValueError("Only concrete equity index futures are supported")
    shared = Path(__file__).resolve().parents[3] / "project/market_data"
    sys.path.insert(0, str(shared))
    from index_strategy.history.downloader import Client
    import pandas as pd
    now = datetime.now(timezone.utc).isoformat()
    client = Client()
    try:
        client.session.upload({"basisSymbols": args.symbols})
        frame = client.session.run('select S_INFO_WINDCODE,S_INFO_LISTDATE,S_INFO_DELISTDATE,OPDATE '
            'from loadTable("dfs://ods_tsdb_wind","cfuturesdescription") '
            'where S_INFO_WINDCODE in basisSymbols')
    finally:
        client.close()
    contracts = []
    for symbol, group in frame.groupby("S_INFO_WINDCODE"):
        row = group.sort_values("OPDATE").iloc[-1]
        if pd.isna(row.S_INFO_LISTDATE) or pd.isna(row.S_INFO_DELISTDATE):
            continue
        contracts.append(dict(instrument_id=symbol, listing_date=str(row.S_INFO_LISTDATE.date()),
            expiry_date=str(row.S_INFO_DELISTDATE.date()), known_at=now,
            source_updated_at=str(row.OPDATE), source="ddb_wind_cfuturesdescription"))
    result = dict(schema_version="cn_index_reference_v1", contracts=contracts, aliases=[],
                  retrieved_at=now, source="dfs://ods_tsdb_wind/cfuturesdescription",
                  limitation="本次下载的修订后合约资料；known_at 为下载时刻，不回填历史可知时间")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    size = args.output.stat().st_size
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    with (args.output.parent / "下载索引.md").open("a", encoding="utf-8") as f:
        f.write(f"\n- {now} | {args.output.name} | {args.output.resolve()} | {result['source']} | 基差看板合约挂牌与到期日 | {size} bytes | SHA256 {digest}\n")
    print(json.dumps(dict(path=str(args.output.resolve()), contracts=len(contracts), bytes=size,
                         missing=sorted(set(args.symbols)-{r['instrument_id'] for r in contracts})), ensure_ascii=False))


if __name__ == "__main__":
    main()
