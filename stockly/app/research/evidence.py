"""Fixed-rule, chronological equity outcome study. No optimized strategy or forecast."""
import math
import statistics
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.analytics.costs import Trade, calculate

IST = ZoneInfo('Asia/Kolkata')

class Candle(BaseModel):
    model_config = ConfigDict(extra='ignore', allow_inf_nan=False)
    date: int = Field(gt=0, le=4102444800)
    open: float = Field(gt=0, le=10000000)
    high: float = Field(gt=0, le=10000000)
    low: float = Field(gt=0, le=10000000)
    close: float = Field(gt=0, le=10000000)
    volume: float = Field(ge=0)

    @model_validator(mode='after')
    def coherent(self):
        if self.high < max(self.open,self.close,self.low) or self.low > min(self.open,self.close):
            raise ValueError('Invalid OHLC ordering')
        return self

class Study(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    symbol: str = Field(min_length=1, max_length=30, pattern=r'^[A-Z0-9&_\-]+(?:\.NS)?$')
    candles: list[Candle] = Field(min_length=30, max_length=50000)
    interval: Literal['5m','15m','1d'] = '1d'
    side: Literal['long','short'] = 'long'
    rule: Literal['above_sma','below_sma','unconditional'] = 'above_sma'
    sma_period: int = Field(default=20, ge=5, le=200)
    horizon_bars: int = Field(default=5, ge=1, le=60)
    quantity: int = Field(default=100, gt=0, le=1000000, strict=True)
    slippage_bps: Decimal = Field(default=Decimal(5), ge=0, le=1000)

    @model_validator(mode='after')
    def supported(self):
        if self.interval == '1d' and self.side == 'short':
            raise ValueError('Daily/overnight short studies unsupported for cash equities.')
        if any(b.date <= a.date for a,b in zip(self.candles,self.candles[1:])):
            raise ValueError('Candles must be strictly chronological with no duplicate timestamps.')
        return self


def summary(trades):
    n = len(trades)
    wins = sum(t['net_profit']>0 for t in trades)
    p = wins/n if n else None
    interval = None
    if n:
        z = 1.959963984540054
        center = (p+z*z/(2*n))/(1+z*z/n)
        half = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
        interval = [max(0,center-half),min(1,center+half)]
    profits = [t['net_profit'] for t in trades]
    positive = sum(max(0,p) for p in profits)
    negative = -sum(min(0,p) for p in profits)
    return {'sample_size':n,'net_wins':wins,'net_losses':sum(p<0 for p in profits),
            'flat':sum(p==0 for p in profits),'historical_net_win_frequency':p,
            'wilson_95_interval_iid_approximation':interval,
            'mean_net_profit_inr':statistics.mean(profits) if n else None,
            'mean_net_return_pct':statistics.mean(t['net_return_pct'] for t in trades) if n else None,
            'profit_factor':positive/negative if negative else None,
            'evidence_status':'insufficient_sample' if n<30 else 'descriptive_only'}


def study(s: Study):
    now = datetime.now(timezone.utc).timestamp()
    intraday = s.interval != '1d'
    seconds = {'5m':300,'15m':900,'1d':86400}[s.interval]
    # Daily bars are accepted only from previous IST dates, avoiding partial sessions.
    today = datetime.now(IST).date()
    bars = [c for c in s.candles if (c.date+seconds <= now if intraday else datetime.fromtimestamp(c.date,IST).date()<today)]
    if len(bars) <= s.sma_period+s.horizon_bars:
        raise ValueError('Insufficient completed candles for configured SMA and horizon.')
    boundary = int(len(bars)*.7)
    closes = [c.close for c in bars]
    prefix = [0.0]
    for x in closes:
        prefix.append(prefix[-1]+x)
    def generate(conditional):
        trades = []
        i = s.sma_period-1
        while i+s.horizon_bars < len(bars):
            entry_i, exit_i = i+1,i+s.horizon_bars
            sma = (prefix[i+1]-prefix[i+1-s.sma_period])/s.sma_period
            match = s.rule=='unconditional' or (closes[i]>sma if s.rule=='above_sma' else closes[i]<sma)
            if conditional and not match:
                i+=1
                continue
            # Purge trades whose labels cross the chronological split.
            if i < boundary <= exit_i:
                i+=1
                continue
            if intraday:
                times = [datetime.fromtimestamp(c.date,IST) for c in bars[i:exit_i+1]]
                # Fixed conservative research cutoff, not a claim about broker's current policy.
                end = datetime.fromtimestamp(bars[exit_i].date+seconds,IST)
                if any(t.date()!=times[0].date() or not time(9,15)<=t.time()<time(15,15) for t in times) or end.date()!=times[0].date() or end.time()>time(15,15) or any(b.date-a.date!=seconds for a,b in zip(bars[i:exit_i],bars[i+1:exit_i+1])):
                    i+=1
                    continue
            if any(c.volume<=0 for c in bars[entry_i:exit_i+1]):
                i+=1
                continue
            result = calculate(Trade(entry=str(bars[entry_i].open),exit=str(bars[exit_i].close),
                                     quantity=s.quantity,side=s.side,
                                     product='intraday' if intraday else 'delivery',slippage_bps=s.slippage_bps))
            trades.append({'signal_at':bars[i].date,'entry_at':bars[entry_i].date,
                           'exit_bar_at':bars[exit_i].date, 'net_profit':result['net_profit'],
                           'net_return_pct':result['return_on_entry_notional_pct'],
                           'partition':'development' if exit_i<boundary else 'holdout'})
            i=exit_i+1
        return trades
    trades,baseline = generate(True),generate(False)
    development = [t for t in trades if t['partition']=='development']
    holdout = [t for t in trades if t['partition']=='holdout']
    train_p = summary(development)['historical_net_win_frequency']
    brier = statistics.mean((train_p-int(t['net_profit']>0))**2 for t in holdout) if train_p is not None and holdout else None
    latest_sma = statistics.mean(closes[-s.sma_period:])
    return {'symbol':s.symbol,'interval':s.interval,'side':s.side,'currency':'INR',
            'rule':s.rule,'sma_period':s.sma_period,'horizon_bars':s.horizon_bars,'quantity':s.quantity,
            'slippage_bps':float(s.slippage_bps), 'data_start':bars[0].date,'data_end':bars[-1].date,
            'completed_candles':len(bars),'excluded_incomplete_or_future':len(s.candles)-len(bars),
            'holdout_start':bars[boundary].date,'all_history':summary(trades),
            'development':summary(development),'holdout':summary(holdout),
            'unconditional_holdout':summary([t for t in baseline if t['partition']=='holdout']),
            'holdout_brier_for_frozen_development_frequency':brier,
            'latest_rule_matches':s.rule=='unconditional' or (closes[-1]>latest_sma if s.rule=='above_sma' else closes[-1]<latest_sma),
            'forecast_probability':None, 'news_conditioned':False,
            'recent_trades':trades[-20:], 'rate_verified_on':'2026-09-10',
            'method':'Signal at completed close, entry at next open, fixed horizon close exit; non-overlapping trades; 70/30 time split with crossing outcomes purged.',
            'limitations':['Historical frequencies are not calibrated forecasts or target-before-stop probabilities.',
                'Wilson intervals assume independent Bernoulli outcomes; market dependence can make them too narrow.',
                '30 trades is a reporting threshold, not proof of statistical power or a tradable edge.',
                'Current Zerodha fees are applied to every historical trade as a cost scenario, not historical fee reconstruction.',
                'No stop/target path, portfolio capital constraint, compounding, liquidity impact, circuit or borrow eligibility model.',
                'Intraday windows must be contiguous within a session and finish by 15:15 IST.',
                'Supplied data may have survivorship, corporate-action and missing-session biases. Daily gaps are retained.',
                'Baseline uses its own non-overlapping schedule; comparison is descriptive, not a matched significance test.',
                'Repeatedly tuning settings against this holdout invalidates its independence. CSCV/PBO is not implemented.']}
