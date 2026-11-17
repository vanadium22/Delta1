"""Incrementally persist recent Wind volume in the same actual-contract daily store."""
from __future__ import annotations

from collections import defaultdict

from ..analytics import ROOTS
from ..sync import segments, valid_value
from ..wind import WindProvider


def refresh_volumes(service, as_of=None, provider_factory=WindProvider):
    start, end = service.window(as_of)
    store = service.store
    provider = None
    requests, saved, errors = 0, 0, []
    with store.writer_lock():
        days = sorted(day for day, opened in store.calendar(start, end).items() if opened)[-80:]
        if not days:
            return {"state": "partial", "requests": 0, "saved": 0, "message": "无已知交易日，未猜测成交量日期"}
        mappings = {key: code for key, code in store.mappings(days[0], days[-1]).items()
                    if key[0] in days and key[1] in ROOTS}
        missing_mappings = len(days)*len(ROOTS)*4-len(mappings)
        quotes = store.quotes(days[0], days[-1])
        required = defaultdict(list)
        for (day, _, _), code in mappings.items():
            if (code, day, "volume") not in quotes:
                required[code].append(day)
        try:
            for code, missing in sorted(required.items()):
                for batch in segments(missing, days):
                    if provider is None:
                        provider = provider_factory(service.config)
                    print(f"补齐成交量 {code} · {batch[0]} 至 {batch[-1]}", flush=True)
                    requests += 1
                    result = provider.series(code, ["volume"], batch[0], batch[-1])
                    rows = []
                    for day in batch:
                        value = result.get(day, {}).get("volume")
                        if valid_value(value, "volume"):
                            rows.append((code, day, "volume", float(value)))
                        else:
                            errors.append(f"{day} {code}.volume 缺失或无效")
                    store.save_rows("quotes", rows)
                    saved += len(rows)
        finally:
            if provider is not None:
                provider.close()
        if missing_mappings:
            errors.append(f"缺少{missing_mappings}个日期/品种/档位映射，未猜测合约")
        return {"state": "partial" if errors else "complete", "requests": requests, "saved": saved,
                "sessions": len(days), "window_start": days[0], "window_end": days[-1],
                "message": "；".join(errors[:8]) if errors else "最近80交易日成交量缺口已补齐，已有有效值未重取"}
