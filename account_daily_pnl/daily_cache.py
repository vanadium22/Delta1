"""Exact day-end checkpoints and calculated daily facts, rebuildable from inputs."""

from collections import defaultdict
from decimal import Decimal
import hashlib
import json

from shared_data.io import atomic_json, sha256

from .baseline import ACCOUNTS, BASE_DAY
from .ledger import Day, Ledger, Movement, ZERO
from .sources import read_source


CACHE_FILENAME = "daily_cache.json"
CACHE_VERSION = 1


def encode(value):
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, dict):
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    return value


def decode(value):
    return Decimal(value["decimal"]) if value.keys() == {"decimal"} else value


def digest(value):
    return hashlib.sha256(json.dumps(encode(value), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def pack_day(frame):
    values = vars(frame).copy()
    for field in ("before", "after"):
        values[field] = [[*key, *legs] for key, legs in sorted(values[field].items())]
    values["movements"] = [[*key, vars(move)] for key, move in sorted(frame.movements.items())]
    values["fee_issues"] = sorted(frame.fee_issues)
    return values


def unpack_day(values):
    fields = values.copy()
    for field in ("before", "after"):
        fields[field] = {(account, code): (long, short) for account, code, long, short in fields[field]}
    fields["movements"] = {(account, code): Movement(**items) for account, code, items in fields["movements"]}
    fields["fee_issues"] = set(fields["fee_issues"])
    return Day(**fields)


def source_hash(path):
    return sha256(path) if path.is_file() else None


def resume(root, days, baseline):
    path = root / CACHE_FILENAME
    baseline_hash = digest(baseline)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_hook=decode)
        if (payload["version"] != CACHE_VERSION or payload["baseline_hash"] != baseline_hash
                or not isinstance(payload["days"], dict)):
            raise ValueError("incompatible checkpoint")
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
        payload = {"version": CACHE_VERSION, "baseline_hash": baseline_hash, "days": {}}
    entries = payload["days"]
    ledger = Ledger(baseline)
    fingerprints = []
    for day in days:
        archive = root / "flows" / f"{day}.xlsx"
        fingerprint = source_hash(archive)
        if fingerprint is None:
            raise FileNotFoundError(f"缺少交易日 {day} 的流水 Excel：{archive}")
        fingerprints.append(fingerprint)

    previous = BASE_DAY
    first = 0
    for day, fingerprint in zip(days, fingerprints):
        entry = entries.get(day)
        saved_frame = entry.get("frame") if isinstance(entry, dict) else None
        if (not isinstance(saved_frame, dict) or entry.get("flow") != fingerprint
                or saved_frame.get("previous_date") != previous):
            break
        previous = day
        first += 1
    todo = days[first:]
    if first:
        frame = unpack_day(entries[previous]["frame"])
        ledger.positions = frame.after.copy()
        ledger.cumulative.update(frame.cumulative)
        ledger.unresolved.update({name: set(items) for name, items in frame.persistent_issues.items()})
        ledger.unresolved_cash.update({name: set(items) for name, items in frame.cash_issues.items()})
        print(f"复用截至 {previous} 的日终持仓检查点。", flush=True)
    if todo:
        for day in [day for day in entries if day >= todo[0]]:
            del entries[day]
        print(f"持仓增量计算 {todo[0]} 至 {todo[-1]}，共 {len(todo)} 个交易日。", flush=True)
    for offset, day in enumerate(todo):
        rows = read_source(root / "flows" / f"{day}.xlsx", "flow", day)
        rows.sort(key=lambda row: (str(row.get("dealDate")), str(row.get("dealTime")), str(row["id"])))
        frame = ledger.advance(day, previous, rows)
        entries[day] = {"flow": fingerprints[first + offset], "frame": pack_day(frame)}
        previous = day
        if (offset + 1) % 30 == 0:
            print(f"持仓已算到 {day}（{offset + 1}/{len(todo)}）", flush=True)
    return ledger, payload


def save(root, payload):
    atomic_json(root / CACHE_FILENAME, encode(payload))


def price_inputs(root, days, config):
    return {day: (source_hash(root / "snapshots" / f"{day}.xlsx"), source_hash(root / "wind" / f"{day}.xlsx"),
                  config.get("wind_futures_field", "settle")) for day in days}


def funding_inputs(days, funding):
    result = {}
    carry = defaultdict(lambda: ZERO)
    for day, previous in zip(days, [BASE_DAY, *days]):
        rows = []
        for account in ACCOUNTS:
            previous_carry = carry[account]
            carry[account] += funding["movements"].get((day, account), ZERO)
            through = funding["confirmed_through"].get(account, "")
            equity = funding["equity"]
            rows.append([funding["opening"].get(account), equity.get((BASE_DAY, account)),
                         equity.get((previous, account)), equity.get((day, account)), previous_carry, carry[account],
                         funding["weighted"].get((day, account), ZERO), through >= previous, through >= day])
        result[day] = digest(rows)
    return result
