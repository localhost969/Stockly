"""NSE cash-equity round-trip charges for a resident individual, per broker.

Statutory rates are the same at every broker; only brokerage and DP charges differ.
All rates checked against each broker's official charges page on 2026-11-16.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

D = Decimal
VERIFIED_ON = '2026-11-16'

# Same for every broker (NSE, SEBI, Govt.). Fractions of traded value.
STATUTORY = {
    'stt_delivery_buy_and_sell': '0.001',     # 0.1%
    'stt_intraday_sell': '0.00025',           # 0.025%
    'nse_transaction': '0.0000307',           # 0.00307% (from 1 Mar 2026)
    'sebi_turnover': '0.000001',              # Rs 10 / crore
    'ipft': '0.000000001',                    # Rs 0.01 / crore
    'stamp_delivery_buy': '0.00015',          # 0.015%
    'stamp_intraday_buy': '0.00003',          # 0.003%
    'gst': '0.18',                            # on brokerage + exchange + SEBI + IPFT (+ DP)
}

# Brokerage per executed order = max(min, min(cap, pct * order value)); pct None = flat cap.
# dp = depository charge per scrip per day on a delivery sell, excluding GST.
BROKERS = {
    'zerodha': {'name': 'Zerodha', 'source': 'https://zerodha.com/charges/',
                'delivery': {'pct': '0', 'cap': '0', 'min': '0'},
                'intraday': {'pct': '0.0003', 'cap': '20', 'min': '0'}, 'dp': '13'},
    'groww':   {'name': 'Groww', 'source': 'https://groww.in/pricing',
                'delivery': {'pct': '0.001', 'cap': '20', 'min': '5'},
                'intraday': {'pct': '0.001', 'cap': '20', 'min': '5'}, 'dp': '20'},
    'upstox':  {'name': 'Upstox', 'source': 'https://upstox.com/brokerage-charges/',
                'delivery': {'pct': None, 'cap': '20', 'min': '0'},
                'intraday': {'pct': '0.001', 'cap': '20', 'min': '0'}, 'dp': '20'},
    'angelone': {'name': 'Angel One', 'source': 'https://www.angelone.in/exchange-transaction-charges',
                 'delivery': {'pct': '0.001', 'cap': '20', 'min': '5'},
                 'intraday': {'pct': '0.001', 'cap': '20', 'min': '5'}, 'dp': '20'},
    'dhan':    {'name': 'Dhan', 'source': 'https://dhan.co/pricing/',
                'delivery': {'pct': '0', 'cap': '0', 'min': '0'},
                'intraday': {'pct': '0.0003', 'cap': '20', 'min': '0'}, 'dp': '12.5'},
}
Broker = Literal['zerodha', 'groww', 'upstox', 'angelone', 'dhan', 'custom']

RATES = {'verified_on': VERIFIED_ON, 'exchange': 'NSE', 'segment': 'cash equity', 'currency': 'INR',
         'statutory': STATUTORY, 'brokers': BROKERS,
         'formula': {'brokerage_per_order': 'max(min, min(cap, pct x order value)); pct null = flat cap',
                     'dp': 'per scrip on a delivery sell, + 18% GST',
                     'stt': 'rounded to the nearest rupee'},
         'notes': ['Promotional offers (e.g. first-30-days free) are ignored.',
                   'Call & trade, auto square-off, AMC, pledge and MTF interest are not included.']}


class Trade(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    entry: Decimal = Field(gt=0, le=10000000)
    exit: Decimal = Field(gt=0, le=10000000)
    quantity: int = Field(gt=0, le=10000000, strict=True)
    side: Literal['long', 'short'] = 'long'
    product: Literal['intraday', 'delivery'] = 'intraday'
    broker: Broker = 'zerodha'
    # used only when broker='custom'
    brokerage_pct: Optional[Decimal] = Field(default=None, ge=0, le=5, description='custom: % of order value, e.g. 0.03')
    brokerage_cap: Optional[Decimal] = Field(default=None, ge=0, le=100000, description='custom: max Rs per order')
    brokerage_min: Optional[Decimal] = Field(default=None, ge=0, le=100000, description='custom: min Rs per order')
    dp_charge: Optional[Decimal] = Field(default=None, ge=0, le=1000, description='custom: DP Rs per delivery sell, excl. GST')
    slippage_bps: Decimal = Field(default=D(0), ge=0, le=1000)
    additional_charges: Decimal = Field(default=D(0), ge=0, le=1000000)

    @model_validator(mode='after')
    def supported(self):
        if self.product == 'delivery' and self.side == 'short':
            raise ValueError('Overnight naked equity shorts are unsupported; use intraday.')
        if self.broker == 'custom' and self.brokerage_pct is None and self.brokerage_cap is None:
            raise ValueError('broker=custom needs brokerage_pct and/or brokerage_cap.')
        return self


def money(x):
    return float(x.quantize(D('.01'), rounding=ROUND_HALF_UP))


def plan(t: Trade):
    """(pct|None, cap|None, min, dp_excl_gst, broker name) for this trade."""
    if t.broker == 'custom':
        pct = t.brokerage_pct / 100 if t.brokerage_pct is not None else None
        return pct, t.brokerage_cap, t.brokerage_min or D(0), t.dp_charge or D(0), 'Custom'
    b = BROKERS[t.broker]; p = b[t.product]
    return (D(p['pct']) if p['pct'] is not None else None), D(p['cap']), D(p['min']), D(b['dp']), b['name']


def order_brokerage(value, pct, cap, floor):
    fee = value * pct if pct is not None else cap
    if pct is not None and cap is not None:
        fee = min(cap, fee)
    return min(value, max(floor, fee)) if fee or floor else D(0)


def calculate(t: Trade):
    S = {k: D(v) for k, v in STATUTORY.items()}
    buy, sell = (t.entry, t.exit) if t.side == 'long' else (t.exit, t.entry)
    buy, sell = buy*t.quantity, sell*t.quantity
    turnover = buy+sell
    delivery = t.product == 'delivery'
    pct, cap, floor, dp, broker_name = plan(t)
    brokerage = order_brokerage(buy, pct, cap, floor) + order_brokerage(sell, pct, cap, floor)
    exchange = turnover*S['nse_transaction']
    sebi, ipft = turnover*S['sebi_turnover'], turnover*S['ipft']
    dp = dp if delivery else D(0)
    charges = {
        'brokerage': brokerage,
        'stt': (turnover*S['stt_delivery_buy_and_sell'] if delivery else sell*S['stt_intraday_sell']).quantize(D('1'), rounding=ROUND_HALF_UP),
        'exchange': exchange, 'sebi': sebi, 'ipft': ipft,
        'gst': (brokerage+exchange+sebi+ipft+dp)*S['gst'],
        'stamp_duty': buy*(S['stamp_delivery_buy'] if delivery else S['stamp_intraday_buy']),
        'dp': dp,
        'additional': t.additional_charges,
    }
    rounded = {k: v.quantize(D('.01'), rounding=ROUND_HALF_UP) for k,v in charges.items()}
    total = sum(rounded.values())
    slippage = (turnover*t.slippage_bps/D(10000)).quantize(D('.01'), rounding=ROUND_HALF_UP)
    gross = sell-buy
    net = gross-total-slippage
    notional = t.entry*t.quantity
    move = abs(t.exit - t.entry)
    breakeven = (total / t.quantity).quantize(D('.01'), rounding=ROUND_HALF_UP)
    return {'currency': 'INR', 'broker': t.broker, 'broker_name': broker_name, 'side': t.side, 'product': t.product,
            'quantity': t.quantity, 'entry_notional': money(notional),
            'buy_value': money(buy), 'sell_value': money(sell), 'turnover': money(turnover),
            'gross_profit': money(gross), 'charges': {k: money(v) for k,v in rounded.items()},
            'total_charges': money(total), 'charges_pct_of_turnover': money(total/turnover*100) if turnover else None,
            'breakeven_move_per_share': float(breakeven), 'estimated_slippage': money(slippage),
            'net_profit': money(net), 'return_on_entry_notional_pct': money(net/notional*100),
            'rate_verified_on': VERIFIED_ON, 'estimate': True,
            'assumptions': ['One executed buy order and one sell order, one scrip, NSE.',
                'Resident individual; DP (+GST) charged once on the delivery sale.',
                'Entry notional is not broker margin. Income tax, AMC, call & trade, auto square-off, MTF interest excluded.',
                'STT rounded per this round trip; contract-note aggregation may differ by a rupee.',
                'Slippage is an extra turnover-based estimate; supplied prices determine statutory charges.']}

class Risk(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    capital: Decimal = Field(gt=0, le=1000000000)
    risk_pct: Decimal = Field(default=D(1), gt=0, le=100)
    entry: Decimal = Field(gt=0, le=10000000)
    stop: Decimal = Field(gt=0, le=10000000)
    target: Decimal = Field(gt=0, le=10000000)
    side: Literal['long', 'short'] = 'long'
    product: Literal['intraday', 'delivery'] = 'intraday'
    broker: Broker = 'zerodha'
    slippage_bps: Decimal = Field(default=D(0), ge=0, le=1000)

    @model_validator(mode='after')
    def levels(self):
        if not (self.stop < self.entry < self.target if self.side == 'long' else self.target < self.entry < self.stop):
            raise ValueError('Stop and target must be on opposite, correct sides of entry.')
        if self.side == 'short' and self.product == 'delivery':
            raise ValueError('Delivery shorts unsupported.')
        return self


def size_position(r: Risk):
    budget = r.capital*r.risk_pct/100
    def outcome(q, price):
        return calculate(Trade(entry=r.entry, exit=price, quantity=q, side=r.side,
                               product=r.product, broker=r.broker, slippage_bps=r.slippage_bps))
    lo, hi = 0, min(10000000, int(r.capital/r.entry), int(budget/abs(r.entry-r.stop)))
    while lo < hi:
        mid = (lo+hi+1)//2
        loss = outcome(mid, r.stop)
        if D(str(-loss['net_profit'])) <= budget and r.entry*mid+D(str(loss['total_charges']))+D(str(loss['estimated_slippage'])) <= r.capital:
            lo = mid
        else:
            hi = mid-1
    stop, target = (outcome(lo, r.stop), outcome(lo, r.target)) if lo else (None, None)
    return {'quantity': lo, 'currency': 'INR', 'risk_budget': money(budget),
            'stop_outcome': stop, 'target_outcome': target,
            'net_reward_to_risk': round(target['net_profit']/-stop['net_profit'], 4) if lo else None,
            'assumptions': ['No leverage; reserves estimated stop-exit charges and slippage.',
                            'Stop fill is assumed at supplied price; gaps can exceed risk budget.']}
