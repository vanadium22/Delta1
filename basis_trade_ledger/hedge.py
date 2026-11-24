from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from .model import DIRECTIONS, ZERO, number


HEDGE_METHODS = {
    'futures': '按期货手数',
    'etf': '按 ETF 份额',
    'adjust_etf': '按当前持仓 · 调整 ETF',
    'adjust_futures': '按当前持仓 · 调整期货',
}


@dataclass(frozen=True)
class HedgeSize:
    etf: Decimal
    futures: Decimal
    raw_etf: Decimal
    raw_futures: Decimal
    etf_notional: Decimal
    futures_notional: Decimal
    residual: Decimal


def _nearest(quantity, unit):
    return (quantity / unit).to_integral_value(rounding=ROUND_HALF_UP) * unit


def hedge_size(method, *, etf_price, basis_price, multiplier, quantity=None, direction='买基差',
               etf_step=100, current_etf=ZERO, current_futures=ZERO):
    cash_unit = number(etf_price, 'ETF 价格')
    basis = number(basis_price, '折算基准价格')
    factor = number(multiplier, '合约乘数', integer=True)
    if not (cash_unit and basis and factor):
        raise ValueError('待补齐 ETF 价格、折算基准价格和合约乘数')
    futures_unit = basis * factor
    existing_etf = existing_futures = ZERO
    if method in ('futures', 'etf'):
        if direction not in ('买基差', '卖基差'):
            raise ValueError('请选择买基差或卖基差')
        anchor = number(quantity, '期货手数' if method == 'futures' else 'ETF 份额', integer=True)
        if anchor is None:
            raise ValueError('填写计划手数或份额后即可换算')
        etf_side, futures_side = DIRECTIONS[direction]
        if method == 'futures':
            raw_etf, raw_futures = anchor * etf_side * futures_unit / cash_unit, anchor * futures_side
        else:
            raw_etf, raw_futures = anchor * etf_side, anchor * futures_side * cash_unit / futures_unit
    elif method in ('adjust_etf', 'adjust_futures'):
        existing_etf, existing_futures = Decimal(current_etf), Decimal(current_futures)
        if method == 'adjust_etf':
            raw_etf = -existing_futures * futures_unit / cash_unit - existing_etf
            raw_futures = ZERO
        else:
            raw_etf = ZERO
            raw_futures = -existing_etf * cash_unit / futures_unit - existing_futures
    else:
        raise ValueError('请选择对冲换算方式')

    etf, futures = raw_etf, raw_futures
    if method in ('futures', 'adjust_etf'):
        step = number(etf_step, 'ETF 份额步长', integer=True)
        if step is None:
            raise ValueError('请填写 ETF 份额步长')
        etf = _nearest(raw_etf, step)
    if method in ('etf', 'adjust_futures'):
        futures = _nearest(raw_futures, Decimal(1))
    residual = (existing_etf + etf) * cash_unit + (existing_futures + futures) * futures_unit
    return HedgeSize(etf, futures, raw_etf, raw_futures, abs(etf) * cash_unit, abs(futures) * futures_unit, residual)
