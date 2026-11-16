from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from app.analytics import market
from app.analytics.costs import Trade, Risk, calculate, size_position, RATES
from app.analytics.technical import analyze
from app.providers import yahoo

router = APIRouter(prefix='/api/analytics', tags=['Analytics (new)'])


def ok(data):
    return {'success': True, 'data': data}


async def get_snapshot(index):
    if index not in market.INDICES:
        raise HTTPException(422, 'Unsupported index; see /api/analytics/catalog')
    try:
        return await market.snapshot(index)
    except Exception:
        raise HTTPException(502, 'NSE snapshot unavailable; retry later.')


@router.get('/catalog')
def catalog():
    return ok({'indices': market.INDICES, 'routes': [
        '/api/analytics/market', '/api/analytics/movers', '/api/analytics/breadth',
        '/api/analytics/technicals/{symbol}', '/api/analytics/charges',
        '/api/analytics/pnl', '/api/analytics/position-size'],
        'scope': 'NSE cash equity analytics; calculators use supplied prices, no order execution.'})


@router.get('/market')
async def market_snapshot(index: str = 'NIFTY 50'):
    return ok(await get_snapshot(index))


@router.get('/movers')
async def movers(index: str = 'NIFTY 50',
                 kind: Literal['gainers','losers','absolute','volume','value','gap_up','gap_down','range'] = 'absolute',
                 limit: int = Query(10, ge=1, le=100)):
    data = await get_snapshot(index)
    rows = data.pop('stocks')
    field = {'gainers':'change_pct','losers':'change_pct','absolute':'change_pct',
             'volume':'volume','value':'traded_value','gap_up':'gap_pct','gap_down':'gap_pct','range':'day_range_pct'}[kind]
    valid = [r for r in rows if r[field] is not None]
    if kind in ('gainers','gap_up'):
        valid = [r for r in valid if r[field]>0]
    if kind in ('losers','gap_down'):
        valid = [r for r in valid if r[field]<0]
    valid.sort(key=lambda r: abs(r[field]) if kind=='absolute' else r[field], reverse=kind not in ('losers','gap_down'))
    return ok({**data, 'kind':kind, 'eligible_count':len(valid), 'returned_count':min(limit,len(valid)), 'stocks':valid[:limit]})


@router.get('/breadth')
async def breadth(index: str = 'NIFTY 50'):
    data = await get_snapshot(index)
    rows = data.pop('stocks')
    changes = [r['change_pct'] for r in rows if r['change_pct'] is not None]
    advances,declines = sum(c>0 for c in changes),sum(c<0 for c in changes)
    return ok({**data,'advances':advances,'declines':declines,'unchanged':sum(c==0 for c in changes),
               'unknown':len(rows)-len(changes),'advance_decline_ratio':advances/declines if declines else None,
               'advance_pct':advances/len(changes)*100 if changes else None,
               'equal_weight_change_pct':sum(changes)/len(changes) if changes else None,
               'at_year_high':[r['symbol'] for r in rows if r['price'] is not None and r['year_high'] is not None and r['price']>=r['year_high']],
               'at_year_low':[r['symbol'] for r in rows if r['price'] is not None and r['year_low'] is not None and r['price']<=r['year_low']]})


@router.get('/technicals/{symbol}')
async def technicals(symbol: str, range: Literal['1mo','3mo','6mo','1y','2y','5d','1d'] = '1y',
                     interval: Literal['1m','5m','15m','30m','1h','1d','1wk','1mo'] = '1d'):
    import re
    symbol = symbol.strip().upper()
    if not re.fullmatch(r'[A-Z0-9&_-]{1,30}(\.NS)?',symbol):
        raise HTTPException(422,'Use an NSE equity symbol, optionally suffixed .NS')
    intraday = interval not in ('1d','1wk','1mo')
    if (range in ('1d','5d') and not intraday) or (interval=='1m' and range not in ('1d','5d')) or (intraday and range not in ('1d','5d','1mo')):
        raise HTTPException(422,'Use 1d/5d for 1m; 1d/5d/1mo for other intraday intervals; 1mo or longer for daily/weekly/monthly.')
    try:
        data = await yahoo.get_history(symbol,range,interval)
    except Exception:
        raise HTTPException(502,'Yahoo candles unavailable; retry later.')
    try:
        return ok(analyze(data))
    except (ValueError,KeyError,TypeError):
        raise HTTPException(502,'Provider returned insufficient or invalid candles.')


@router.get('/charges')
def charges():
    return ok(RATES)


@router.post('/pnl')
def pnl(trade: Trade):
    return ok(calculate(trade))


@router.post('/position-size')
def position_size(risk: Risk):
    return ok(size_position(risk))
