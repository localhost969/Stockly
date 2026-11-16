import math
import statistics
from datetime import datetime
from zoneinfo import ZoneInfo


def ema(values, period):
    if len(values) < period:
        return []
    result = [statistics.mean(values[:period])]
    for value in values[period:]:
        result.append(result[-1]+2/(period+1)*(value-result[-1]))
    return result


def analyze(data):
    candles = []
    seen = set()
    for c in sorted(data['candles'], key=lambda c: c.get('date') or 0):
        fields = [c.get(k) for k in ('date','open','high','low','close','volume')]
        if not all(isinstance(v, (int,float)) and math.isfinite(v) for v in fields):
            continue
        if min(fields[1:5]) <= 0 or c['volume'] < 0 or c['low'] > min(c['open'],c['close']) or c['high'] < max(c['open'],c['close']) or c['date'] in seen:
            continue
        candles.append(c)
        seen.add(c['date'])
    if len(candles) < 2:
        raise ValueError('At least two valid candles required')
    close = [c['close'] for c in candles]
    def last(values):
        return round(values[-1],6) if values else None
    sma = {str(p): round(statistics.mean(close[-p:]),6) if len(close)>=p else None for p in (20,50,200)}
    rs = None
    atr = None
    if len(close)>=15:
        changes = [b-a for a,b in zip(close,close[1:])]
        gain = statistics.mean(max(c,0) for c in changes[:14])
        loss = statistics.mean(max(-c,0) for c in changes[:14])
        for c in changes[14:]:
            gain,loss = (gain*13+max(c,0))/14,(loss*13+max(-c,0))/14
        rs = 100-100/(1+gain/loss) if loss else (100 if gain else 50)
        tr = [max(c['high']-c['low'],abs(c['high']-p['close']),abs(c['low']-p['close'])) for p,c in zip(candles,candles[1:])]
        atr = statistics.mean(tr[:14])
        for value in tr[14:]:
            atr = (atr*13+value)/14
    fast,slow = ema(close,12),ema(close,26)
    macd = [a-b for a,b in zip(fast[14:],slow)]
    signal = ema(macd,9)
    band = None
    if len(close)>=20:
        mid,sd = statistics.mean(close[-20:]),statistics.pstdev(close[-20:])
        band = {'middle':mid,'upper':mid+2*sd,'lower':mid-2*sd}
    session = datetime.fromtimestamp(candles[-1]['date'],ZoneInfo('Asia/Kolkata')).date()
    day = [c for c in candles if datetime.fromtimestamp(c['date'],ZoneInfo('Asia/Kolkata')).date()==session]
    vol = sum(c['volume'] for c in day)
    intraday = data['interval'] not in ('1d','1wk','1mo','3mo','5d')
    returns = [math.log(b/a) for a,b in zip(close,close[1:])]
    peak,drawdown = close[0],0
    for price in close:
        peak = max(peak,price)
        drawdown = min(drawdown,(price/peak-1)*100)
    previous = candles[-2]
    pivot = (previous['high']+previous['low']+previous['close'])/3
    priorvol = [c['volume'] for c in candles[-21:-1]]
    return {'symbol':data['symbol'],'source':data['source'],'interval':data['interval'],
            'as_of':candles[-1]['date'],'timestamp_unit':'unix_seconds', 'currency':data.get('meta',{}).get('currency'),
            'candles_used':len(close),'candles_dropped':len(data['candles'])-len(close),
            'close':close[-1], 'sma':sma,'ema':{str(p):last(ema(close,p)) for p in (9,21,50)},
            'rsi_14_wilder':rs,'atr_14_wilder':atr,
            'macd':{'line':last(macd),'signal':last(signal),'histogram':macd[-1]-signal[-1] if signal else None},
            'bollinger_20_2':band,
            'session_vwap':sum((c['high']+c['low']+c['close'])/3*c['volume'] for c in day)/vol if vol and intraday else None,
            'relative_volume_20_bars':candles[-1]['volume']/statistics.mean(priorvol) if len(priorvol)==20 and sum(priorvol)>0 else None,
            'period_return_pct':(close[-1]/close[0]-1)*100,
            'max_close_drawdown_pct':drawdown,
            'volatility_per_bar_pct':statistics.stdev(returns)*100 if len(returns)>1 else None,
            'annualized_volatility_pct':statistics.stdev(returns)*math.sqrt(252)*100 if len(returns)>1 and data['interval']=='1d' else None,
            'window_high':max(c['high'] for c in candles),'window_low':min(c['low'] for c in candles),
            'previous_bar_pivots':{'pivot':pivot,'r1':2*pivot-previous['low'],'s1':2*pivot-previous['high'],
                                   'r2':pivot+previous['high']-previous['low'],'s2':pivot-previous['high']+previous['low']},
            'warnings':['Unadjusted OHLC; splits/dividends can distort indicators. Last candle may be incomplete.',
                        'Null means insufficient data. Volume ratio compares bars, not time-of-day sessions.',
                        'VWAP uses typical candle price for latest IST session; it is an approximation.']}
