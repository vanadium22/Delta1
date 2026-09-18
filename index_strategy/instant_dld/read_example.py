"""Read a live DataFrame and optionally save a derived table in its own directory."""
import argparse

from .reader import RealtimeReader, write_strategy_frame
from .realtime_store import DEFAULT_OUTPUT


def main():
    parser = argparse.ArgumentParser(description="读取实时 DataFrame；可演示独立保存买卖中间价计算结果")
    parser.add_argument("--root", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--symbol", nargs="+", default=["AU2610.SHF"])
    parser.add_argument("--save-result", action="store_true")
    args = parser.parse_args()
    reader = RealtimeReader(args.root)
    frame = reader.latest(args.symbol)
    print(frame[["symbol", "close", "volume", "volume_interval_seconds", "volume_total",
                 "bid_price_1", "bid_volume_1", "ask_price_1", "ask_volume_1"]].to_string())
    if args.save_result and not frame.empty:
        result = frame[["sequence", "symbol", "close"]].copy()
        result["mid_price"] = (frame["bid_price_1"] + frame["ask_price_1"]) / 2
        print(write_strategy_frame(result, "read_example", args.root))


if __name__ == "__main__":
    main()
