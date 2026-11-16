import asyncio
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError
from app.providers import yahoo
from app.research import search
from app.research.evidence import Candle, Study, study
from app.research.guide import GUIDE

router = APIRouter(prefix='/api/research', tags=['Equity research'])


def ok(data):
    return {'success':True,'data':data}


@router.get('/guide')
def guide():
    return ok(GUIDE)


@router.get('/news')
async def news(q: str = Query(...,min_length=3,max_length=300),
               days: int = Query(7,ge=1,le=90),limit: int = Query(20,ge=1,le=100)):
    try:
        return ok(await search.news(q,days,limit))
    except Exception:
        raise HTTPException(502,'News provider unavailable or query rejected; retry or simplify query.')


@router.get('/search')
async def web_search(q: str = Query(...,min_length=3,max_length=300),limit: int = Query(10,ge=1,le=20)):
    try:
        return ok(await search.web_search(q,limit))
    except LookupError:
        raise HTTPException(503,'Set BRAVE_SEARCH_API_KEY to enable web search.')
    except Exception:
        raise HTTPException(502,'Web search provider unavailable.')


@router.post('/evidence')
def evidence(request: Study):
    try:
        return ok(study(request))
    except ValueError as e:
        raise HTTPException(422,str(e))


async def historical_data(symbol, interval, range_, side, rule, horizon, quantity, slippage):
    import re
    symbol=symbol.strip().upper()
    if not re.fullmatch(r'[A-Z0-9&_\-]{1,25}(\.NS)?',symbol):
        raise HTTPException(422,'Use an NSE cash equity symbol.')
    if interval!='1d' and range_ not in ('5d','1mo'):
        raise HTTPException(422,'Intraday history supports 5d or 1mo here.')
    if interval=='1d' and (range_=='5d' or side=='short'):
        raise HTTPException(422,'Daily studies require 1mo or longer and long side.')
    try:
        raw=await yahoo.get_history(symbol,range_,interval)
        valid=[]
        for row in raw['candles']:
            try:
                valid.append(Candle.model_validate(row))
            except ValidationError:
                pass
        valid.sort(key=lambda c:c.date)
        request=Study(symbol=symbol,candles=valid,interval=interval,side=side,rule=rule,
                      horizon_bars=horizon,quantity=quantity,slippage_bps=slippage)
        result=await asyncio.to_thread(study,request)
        result.update(source='yahoo',requested_range=range_,provider_candles=len(raw['candles']),
                      invalid_candles_dropped=len(raw['candles'])-len(valid),
                      data_coverage='Available provider history only; not all historical market data.')
        return result
    except (ValidationError,ValueError):
        raise HTTPException(502,'Provider history has insufficient or invalid candles for this study.')
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502,'Historical provider unavailable.')


@router.get('/historical/{symbol}')
async def historical(symbol: str, interval: Literal['5m','15m','1d']='1d',
                     range: Literal['5d','1mo','1y','2y','5y','10y','max']='5y',
                     side: Literal['long','short']='long',
                     rule: Literal['above_sma','below_sma','unconditional']='above_sma',
                     horizon_bars: int=Query(5,ge=1,le=60),quantity: int=Query(100,ge=1,le=1000000),
                     slippage_bps: float=Query(5,ge=0,le=1000,allow_inf_nan=False)):
    return ok(await historical_data(symbol,interval,range,side,rule,horizon_bars,quantity,slippage_bps))
