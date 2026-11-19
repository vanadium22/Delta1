"""Roll positions and compute mark-to-market P&L independently of funding."""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from .baseline import ACCOUNTS, ACCOUNT_IDS


ZERO = Decimal(0)
FUTURES_MULTIPLIERS = {"IF": 300, "IH": 300, "IC": 200, "IM": 200}
NO_POSITION = (ZERO, ZERO)
POSITIONS = ("交易日", "账户", "标的", "期初多仓", "期初空仓", "期末多仓", "期末空仓", "期末净仓",
             "前日价格", "前日来源", "日终价格", "日终来源", "乘数", "买入金额", "卖出金额", "费用",
             "现金分红", "净市值或名义额", "单日盈亏", "状态")
SUMMARY = ("交易日", "账户", "现货市值", "期货净名义额", "单日盈亏", "当日净入金", "总权益", "参考权益", "状态")


def money(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("金额或数量字段为空或无效。") from exc
    if not number.is_finite():
        raise ValueError("金额或数量必须为有限值。")
    return number


def multiplier(code):
    if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code):
        return 1
    future = re.fullmatch(r"(IF|IH|IC|IM)\d{4}\.CFE", code)
    if future:
        return FUTURES_MULTIPLIERS[future[1]]
    raise ValueError(f"标的 {code} 未配置合约乘数。")


def net(position):
    return position[0] - position[1]


@dataclass
class Movement:
    buys: Decimal = ZERO
    sells: Decimal = ZERO
    fees: Decimal = ZERO
    dividend: Decimal = ZERO

    @property
    def cash(self):
        return self.sells - self.buys - self.fees + self.dividend


@dataclass
class Day:
    date: str
    previous_date: str
    before: dict
    after: dict
    movements: dict
    cumulative: dict
    current_issues: dict
    persistent_issues: dict
    cash_issues: dict
    book_issues: list

    def valuation_keys(self):
        return ({(self.previous_date, code) for (_, code), legs in self.before.items() if net(legs)}
                | {(self.date, code) for (_, code), legs in self.after.items() if legs != NO_POSITION})


class Ledger:
    def __init__(self, baseline):
        self.initial = {}
        self.initial_prices = {}
        self.initial_values = defaultdict(Decimal)
        for row in baseline["positions"]:
            account, code = row["account"], row["code"]
            qty = money(row["quantity"])
            price = money(row["price"])
            if qty < 0 or price <= 0:
                raise ValueError(f"{account} 基准数量或价格无效。")
            long, short = self.initial.get((account, code), NO_POSITION)
            if row["side"] == "long":
                long += qty
            elif row["side"] == "short":
                short += qty
            else:
                raise ValueError(f"{account} 基准多空字段无效。")
            self.initial[account, code] = long, short
            old = self.initial_prices.setdefault((account, code), price)
            if old != price:
                raise ValueError(f"{account} {code} 的基准价格不一致。")
        for (account, code), legs in self.initial.items():
            self.initial_values[account] += net(legs) * self.initial_prices[account, code] * multiplier(code)
        self.positions = self.initial.copy()
        self.cumulative = defaultdict(Decimal)
        self.unresolved = defaultdict(set)
        self.unresolved_cash = defaultdict(set)

    def advance(self, day, previous_day, rows):
        before = self.positions.copy()
        moves = defaultdict(Movement)
        issues = defaultdict(list)
        identifiers = set()
        book_issues = []
        for row in rows:
            if row["id"] in identifiers or not row["id"]:
                raise ValueError(f"{day} 出现重复或空白流水 ID。")
            identifiers.add(row["id"])
            account = ACCOUNT_IDS.get(row["tradeAccount"])
            if account is None:
                if not row["tradeAccount"]:
                    book_issues.append(f"{day} {row['instrumentId']} {row['type']} #{row['id']} 未提供交易账户。")
                continue
            code = str(row["instrumentId"]).upper()
            kind = row["type"]
            try:
                if row["currencyCode"] != "CNY":
                    raise ValueError("未配置非人民币流水。")
                if kind == "TRADE":
                    self.trade(account, code, row, moves[account, code])
                elif kind == "DIVIDEND":
                    self.dividend(row, moves[account, code])
                elif kind == "BONUS":
                    self.bonus(account, code, row)
                else:
                    raise ValueError(f"尚未核实流水类型 {kind} 的入账方式。")
            except ValueError as exc:
                message = f"{day} {code} {kind} #{row['id']}：{exc}"
                issues[account].append(message)
                if kind != "DIVIDEND":
                    self.unresolved[account].add(message)
                self.unresolved_cash[account].add(message)
        for (account, code), sides in self.positions.items():
            if min(sides) < 0:
                issues[account].append(f"{day} {code} 期货方向持仓为负，需核对开平或基准。")
        for (account, _), move in moves.items():
            self.cumulative[account] += move.cash
        return Day(day, previous_day, before, self.positions.copy(), dict(moves), dict(self.cumulative),
                   dict(issues), {account: tuple(sorted(messages)) for account, messages in self.unresolved.items()},
                   {account: len(messages) for account, messages in self.unresolved_cash.items()}, book_issues)

    def trade(self, account, code, row, move):
        factor = multiplier(code)
        qty, price = money(row["dealAmount"]), money(row["dealPrice"])
        side, flag = row["direction"], row["openClose"]
        if qty <= 0 or price <= 0 or side not in {"BUYER", "SELLER"}:
            raise ValueError("成交数量、价格或买卖方向无效。")
        gross = money(row["dealBalance"])
        if gross <= 0 or abs(gross - qty * price * factor) > Decimal("0.05"):
            raise ValueError("成交金额和数量、价格、乘数无法对账。")
        if row["fee"] is None:
            fee = (money(row["dealBalanceWithFee"]) - gross) * (1 if side == "BUYER" else -1)
        else:
            fee = money(row["fee"])
        if fee < 0:
            raise ValueError("成交费用为负。")
        if row["dealBalanceWithFee"] is not None:
            expected = gross + fee if side == "BUYER" else gross - fee
            if abs(money(row["dealBalanceWithFee"]) - expected) > Decimal("0.01"):
                raise ValueError("费后金额与成交金额、费用无法对账。")
        long, short = self.positions.get((account, code), NO_POSITION)
        if code.endswith(".CFE"):
            if flag not in {"OPEN", "CLOSE"}:
                raise ValueError("期货开平方向无效。")
            if (side, flag) == ("BUYER", "OPEN"):
                long += qty
            elif (side, flag) == ("SELLER", "CLOSE"):
                long -= qty
            elif (side, flag) == ("SELLER", "OPEN"):
                short += qty
            else:
                short -= qty
        else:
            holding = long - short + (qty if side == "BUYER" else -qty)
            long, short = max(ZERO, holding), max(ZERO, -holding)
        if (long, short) == NO_POSITION:
            self.positions.pop((account, code), None)
        else:
            self.positions[account, code] = long, short
        if side == "BUYER":
            move.buys += gross
        else:
            move.sells += gross
        move.fees += fee

    def bonus(self, account, code, row):
        qty = money(row["dealAmount"])
        if (multiplier(code) != 1 or row["direction"] != "BUYER" or row["openClose"] != "OPEN" or qty <= 0
                or any(row[field] not in (0, None) for field in ("dealPrice", "dealBalance", "dealBalanceWithFee", "fee"))):
            raise ValueError("送转股份与已核实的流水格式不一致。")
        long, short = self.positions.get((account, code), NO_POSITION)
        self.positions[account, code] = long + qty, short

    @staticmethod
    def dividend(row, move):
        gross = money(row["dealBalance"])
        if money(row["dealAmount"]) != 0 or gross < 0:
            raise ValueError("现金分红的数量或金额与已核实样本不同。")
        fee = money(row["fee"]) if row["fee"] is not None else ZERO
        if fee < 0 or fee > gross:
            raise ValueError("现金分红费用无效。")
        move.dividend += gross
        move.fees += fee


def total(values):
    return sum(values, ZERO) if all(value is not None for value in values) else None


def rounded(value):
    return None if value is None else value.quantize(Decimal("0.01"))


def snapshot_checks(day, rows):
    modeled = defaultdict(Decimal)
    for (_, code), legs in day.after.items():
        modeled[code] += net(legs)
    book = {}
    missing = set()
    for row in rows:
        if row["currencyCode"] == "CNY":
            code = row["instrumentId"].upper()
            try:
                book[code] = money(row["netPosition"])
            except ValueError:
                missing.add(code)
    differences = [(code, modeled[code], book.get(code, ZERO)) for code in sorted((modeled.keys() | book.keys()) - missing)
                   if abs(modeled[code] - book.get(code, ZERO)) > Decimal("0.0001")]
    checks = [(day.date, "账簿", f"三账户合计与 BCT 账簿快照有 {len(differences)} 个标的净持仓差异。")]
    checks.extend((day.date, "账簿", f"{code} 三账户 {model}，BCT 账簿 {actual}。")
                  for code, model, actual in differences)
    checks.extend((day.date, "账簿", f"{code} 缺少 BCT 快照净持仓。") for code in sorted(missing))
    return checks


def report(day, ledger, baseline, prices, funding):
    details = []
    overview = []
    checks = [(day.date, "账簿", issue) for issue in day.book_issues]
    for account in ACCOUNTS:
        positions = sorted({key for key in day.before.keys() | day.after.keys() | day.movements.keys()
                            if key[0] == account})
        daily_pnl, marked_values, spot, futures = [], [], [], []
        issues = list(day.current_issues.get(account, ()))
        unknown_replay = day.persistent_issues.get(account, ())
        unresolved_prices = 0
        mixed_futures = False
        for key in positions:
            code = key[1]
            before = day.before.get(key, NO_POSITION)
            after = day.after.get(key, NO_POSITION)
            move = day.movements.get(key, Movement())
            previous = (ledger.initial_prices.get(key), "基准持仓:最新价") if day.previous_date == baseline["day"] else (
                prices.get((day.previous_date, code), (None, None)))
            current = prices.get((day.date, code), (None, None))
            try:
                factor = multiplier(code)
            except ValueError:
                factor = None
            prev_value = ZERO if not net(before) else (None if previous[0] is None or factor is None
                                                       else net(before) * previous[0] * factor)
            end_value = ZERO if not net(after) else (None if current[0] is None or factor is None
                                                    else net(after) * current[0] * factor)
            pnl = None if prev_value is None or end_value is None else end_value - prev_value + move.cash
            state = []
            if pnl is None or after != NO_POSITION and current[0] is None:
                unresolved_prices += 1
                state.append("缺前日或日终价格")
            if (code.endswith(".CFE") and net(before) and net(after) and previous[1] and current[1]
                    and previous[1] != current[1]):
                mixed_futures = True
                state.append("估值来源变化")
            if min(*before, *after) < 0:
                state.append("开平数量待对账")
            daily_pnl.append(pnl)
            marked_values.append(end_value)
            (futures if code.endswith(".CFE") else spot).append(end_value)
            details.append((day.date, account, code, *before, *after, net(after), *previous, *current,
                            factor, rounded(move.buys), rounded(move.sells), rounded(move.fees), rounded(move.dividend),
                            rounded(end_value), rounded(pnl), "；".join(state)))
        if unresolved_prices:
            issues.append(f"{unresolved_prices} 个标的存在价格缺项")
        if mixed_futures:
            issues.append("期货估值来源变化，核对 BCT 价格与 Wind 选取字段")
        if unknown_replay:
            issues.append(f"{len(unknown_replay)} 条累计流水需核对")
        account_pnl = total(daily_pnl) if not unknown_replay and not day.current_issues.get(account) else None
        equity = None
        reference = None
        closing = total(marked_values)
        starting_funds = funding["opening"].get(account)
        complete = funding["confirmed_through"].get(account, "") >= day.date
        deposits = sum((amount for (stamp, name), amount in funding["movements"].items()
                        if name == account and baseline["day"] < stamp <= day.date), ZERO)
        if closing is not None and not day.cash_issues.get(account) and not day.current_issues.get(account):
            change = closing - ledger.initial_values[account] + day.cumulative.get(account, ZERO) + deposits
            if starting_funds is not None and complete:
                equity = starting_funds + change
            else:
                candidate = starting_funds if starting_funds is not None else baseline["equity_candidates"].get(account)
                if candidate is not None:
                    reference = money(candidate) + change
        if starting_funds is None or not complete:
            issues.append("基准权益或资金流水覆盖待确认")
        overview.append((day.date, account, rounded(total(spot)), rounded(total(futures)), rounded(account_pnl),
                         rounded(funding["movements"].get((day.date, account), ZERO)) if complete else None,
                         rounded(equity), rounded(reference), "；".join(issues)))
        checks.extend((day.date, account, message) for message in issues)
        checks.extend((day.date, account, message) for message in unknown_replay if message not in issues)
    combined = (day.date, "合计", *(total([row[i] for row in overview]) for i in range(2, 8)),
                "；".join(row[1] for row in overview if row[-1]))
    overview.append(combined)
    return overview, details, checks
