"""Account-level performance, equity reconciliation and reporting periods."""

from datetime import date
from decimal import Decimal

from .baseline import ACCOUNTS, BASE_DAY
from .ledger import SUMMARY_FIELDS, ZERO, rounded, total


PERIOD_COLUMNS = ("期间", "账户", "起始交易日", "截止交易日", "累计净盈亏", "手续费合计",
                  "累计收益率", "期末总权益", "盈亏有值天数", "手续费有值天数", "交易日总数", "累计盈亏来源")
AMOUNTS = ("spot", "futures", "pnl", "net_flow", "equity", "reference", "prior_equity", "equity_pnl",
           "gross_pnl", "fees", "modeled_pnl", "difference", "denominator", "history_pnl", "ytd_pnl")


def opening_equity(funding, account):
    return funding["equity"].get((BASE_DAY, account), funding["opening"].get(account))


def period_pnl(row, start, funding):
    day, account = row["day"], row["account"]
    anchor = opening_equity(funding, account) if start is None else funding["equity"].get((start["day"], account))
    prior_day = BASE_DAY if start is None else start["day"]
    if (row["equity_source"] == "结算单" and anchor is not None
            and funding["confirmed_through"].get(account, "") >= day):
        flows = sum((amount for (stamp, name), amount in funding["movements"].items()
                     if name == account and prior_day < stamp <= day), ZERO)
        return row["equity"] - anchor - flows, "结算权益差"
    modeled_anchor = ZERO if start is None else start["modeled_history"]
    if row["modeled_history"] is not None and modeled_anchor is not None:
        return row["modeled_history"] - modeled_anchor, "成交估值"
    return None, None


class Performance:
    def __init__(self, funding, compound):
        self.funding = funding
        self.compound = compound
        self.year = None
        self.year_anchor = {}
        self.previous = {}
        self.history_factors = {}
        self.year_factors = {}

    def apply(self, accounts):
        year = accounts[0]["day"][:4]
        if year != self.year:
            self.year_anchor = self.previous
            self.year_factors = {}
            self.year = year
        for row in accounts:
            account = row["account"]
            row["history_pnl"], row["history_source"] = period_pnl(row, None, self.funding)
            row["ytd_pnl"], row["ytd_source"] = period_pnl(row, self.year_anchor.get(account), self.funding)
        combined = {key: total([row[key] for row in accounts]) for key in AMOUNTS}
        for amount, source in (("pnl", "pnl_source"), ("equity", "equity_source"),
                               ("prior_equity", "prior_source"),
                               ("history_pnl", "history_source"), ("ytd_pnl", "ytd_source")):
            used = {row[source] for row in accounts if row[source]}
            combined[source] = (next(iter(used)) if len(used) == 1 else "账户来源混合") if combined[amount] is not None else None
        combined["day"] = accounts[0]["day"]
        combined["account"] = "合计"
        combined["status"] = "；".join(row["account"] for row in accounts if row["status"])
        combined["day_return"] = (combined["pnl"] / combined["denominator"] if
                                  combined["pnl"] is not None and combined["denominator"] else None)
        self.previous = {row["account"]: row for row in accounts}
        result = [*accounts, combined]
        for row in result:
            account = row["account"]
            row["history_return"] = self.link(self.history_factors, account, row["day_return"])
            row["ytd_return"] = self.link(self.year_factors, account, row["day_return"])
        return result

    def link(self, factors, account, daily):
        previous = factors.get(account, Decimal(1))
        if not self.compound or previous is None or daily is None or daily < -1:
            factors[account] = None
            return None
        factors[account] = previous * (1 + daily)
        return factors[account] - 1


RATE_KEYS = {"day_return", "history_return", "ytd_return"}
TEXT_KEYS = {"account", "pnl_source", "equity_source", "prior_source", "history_source", "ytd_source", "status"}


def sheet_rows(rows):
    for row in rows:
        yield tuple(date.fromisoformat(row[key]) if key == "day" else row[key] if key in RATE_KEYS | TEXT_KEYS
                    else rounded(row[key]) for key, _ in SUMMARY_FIELDS)


def period_summary(timeline):
    year = timeline[-1]["day"][:4]
    current_year = [row for row in timeline if row["day"].startswith(year)]
    records = []
    for label, subset, metric, rate, source in (
        ("历史至今", timeline, "history_pnl", "history_return", "history_source"),
        (f"{year}年内", current_year, "ytd_pnl", "ytd_return", "ytd_source"),
    ):
        for account in (*ACCOUNTS, "合计"):
            rows = [row for row in subset if row["account"] == account]
            first, last = rows[0], rows[-1]
            records.append((label, account, date.fromisoformat(first["day"]), date.fromisoformat(last["day"]),
                            rounded(last[metric]), rounded(total([row["fees"] for row in rows])), last[rate],
                            rounded(last["equity"]), sum(row["pnl"] is not None for row in rows),
                            sum(row["fees"] is not None for row in rows), len(rows), last[source]))
    return records, current_year
