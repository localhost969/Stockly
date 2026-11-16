"""One-stock context for agents, and the per-stock report page (/stocks/{SYMBOL})."""
import json
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from app.home.routes import STATIC
from app.stock import context as cx

router = APIRouter(tags=['Stock'])


@router.get('/api/stock/{symbol}', summary='Everything about one stock: quote, company, valuation, every index it belongs to')
async def stock(symbol: str, refresh: bool = Query(False, description='Bypass the 30 s / 10 min cache.')):
    """Price (OHLC, VWAP, 52-week high/low with dates, circuit band, volatility), trading (volume,
    value, delivery %), company (sector, industry, market cap), P/E vs sector P/E, and **every NSE index
    the stock is in** with that index's move today and `stock_minus_index_pct`. Also returns links,
    whether an agent report exists, and `next_calls` for news, fundamentals and technicals."""
    try:
        return {'success': True, 'data': await cx.context(symbol, force=refresh)}
    except ValueError as e:
        raise HTTPException(422, str(e))
    except cx.NotFound as e:
        raise HTTPException(404, str(e))
    except Exception:
        raise HTTPException(502, 'NSE quote unavailable; retry later.')


@router.get('/api/stock/{symbol}/filings', summary='Official NSE filings: announcements, corporate actions, board meetings')
async def stock_filings(symbol: str, days: int = Query(30, ge=1, le=365, description='Announcements from the last N days'),
                        limit: int = Query(20, ge=1, le=100)):
    """Exchange announcements (results, orders, meetings, disclosures, each with its PDF), the last
    10 corporate actions (dividends, splits, bonus) and board meetings, plus `upcoming` events.
    Use alongside `/api/research/news`: filings are what the company officially said."""
    try:
        return {'success': True, 'data': await cx.filings(symbol, days, limit)}
    except ValueError as e:
        raise HTTPException(422, str(e))
    except cx.NotFound as e:
        raise HTTPException(404, str(e))
    except Exception:
        raise HTTPException(502, 'NSE filings unavailable; retry later.')


@router.get('/stocks/{symbol}', include_in_schema=False)
def report_page(symbol: str):
    return FileResponse(STATIC / 'stock.html', media_type='text/html', headers={'Cache-Control': 'no-cache'})


@router.get('/stocks/{symbol}/report.json', tags=['Stock'], summary="The agent's saved report for a stock (stocks/<SYMBOL>/report.json)")
def report_json(symbol: str):
    try:
        symbol = cx.clean(symbol)
    except ValueError as e:
        raise HTTPException(422, str(e))
    f = cx.STOCKS_DIR / symbol / 'report.json'
    if not f.exists():
        raise HTTPException(404, f'No report yet. An agent writes stocks/{symbol}/report.json (see AGENTS.md).')
    try:
        return JSONResponse(json.loads(f.read_text()), headers={'Cache-Control': 'no-cache'})
    except json.JSONDecodeError as e:
        raise HTTPException(500, f'stocks/{symbol}/report.json is not valid JSON: {e}')
