from pathlib import Path
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import PlainTextResponse, JSONResponse, HTMLResponse, RedirectResponse
import asyncio
try:
    from app.providers import yahoo, nse, screener
except:
    from providers import yahoo, nse, screener

DESCRIPTION = """
Indian (NSE) stock market data for AI agents — live prices, candles, fundamentals, analytics and
research evidence — plus a live market dashboard for humans at **[/](/)**.

**Start here**
- Agents: read `AGENTS.md` in the workspace (also `GET /api.md` for this reference as markdown, with sample outputs).
- One stock: `GET /api/stock/{symbol}` first, then news / fundamentals / technicals from its `next_calls`.
- Humans: open **[/](/)** in a browser.

**Conventions**
- Symbols are NSE codes (`RELIANCE`, `TCS`, `M&M`); `.NS` is optional.
- Success: `{"success": true, "data": ...}` (except `/api/screener`, which returns markdown).
- Errors: `{"detail": "..."}` — `422` bad input, `404` unknown, `502` upstream provider failed.
- Prices in INR. Percentages are percentage points (`2` = 2%). Missing values are `null`.
- Public NSE/Yahoo/Screener data can be delayed. Not investment advice.
"""

TAGS = [
    {"name": "Market overview", "description": "The home dashboard's data: indices, breadth, sectors, movers, symbol list."},
    {"name": "Stock", "description": "One call per stock: quote, company, valuation and every index it belongs to; the agent's saved report."},
    {"name": "Market data", "description": "Live quote, OHLCV candles and Screener.in fundamentals."},
    {"name": "Analytics (new)", "description": "Index snapshots, movers, breadth, technicals, and trade-cost calculators for Zerodha, Groww, Upstox, Angel One, Dhan or custom rates."},
    {"name": "Equity research", "description": "News, web search and historical rule evidence."},
    {"name": "Meta", "description": "Health and discovery."},
]

ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(
    title="Stockly API",
    version="2.0",
    description=DESCRIPTION,
    openapi_tags=TAGS,
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DOCS_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stockly API</title><style>body{margin:0;background:#fff}</style></head>
<body><script id="api-reference" data-url="/openapi.json" data-configuration='{"theme":"default","darkMode":false,"hideDarkModeToggle":true,"layout":"modern","hideDownloadButton":false,"metaData":{"title":"Stockly API"}}'></script>
<script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference@1.25.0/dist/browser/standalone.min.js"></script>
</body></html>"""


@app.get("/docs", include_in_schema=False)
def docs():
    return HTMLResponse(DOCS_HTML)


@app.get("/swagger", include_in_schema=False)
def swagger():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Stockly API · Swagger")


@app.get("/api.md", include_in_schema=False)
def api_markdown():
    return PlainTextResponse((ROOT / "API.md").read_text(), media_type="text/markdown; charset=utf-8")


@app.get("/", tags=["Meta"], summary="Discovery JSON (browsers get the dashboard)")
def root(request: Request):
    if "text/html" in request.headers.get("accept", ""):
        return home_page()
    return {
        "status": "ok",
        "name": "Stockly",
        "version": "2.0",
        "dashboard": "/  (open in a browser)",
        "docs": "/docs (interactive)  |  /api.md (markdown)  |  /openapi.json",
        "endpoints": {
            "live": "/api/live/{symbol}",
            "history": "/api/history/{symbol}?range=1y&interval=1d",
            "screener": "/api/screener/{symbol}  (text/markdown)",
            "overview": "/api/market/overview",
            "stock": "/api/stock/{symbol}",
            "stock_report_page": "/stocks/{symbol}",
            "symbols": "/api/market/symbols",
            "analytics": "/api/analytics/catalog",
            "research": "/api/research/guide",
        },
    }

@app.get("/health", tags=["Meta"], summary="Liveness check")
def health():
    return {"status": "ok"}

@app.get("/api/live/{symbol}", tags=["Market data"], summary="Live price (Yahoo, NSE fallback)")
async def live_price(symbol: str):
    # Try Yahoo first (fast, stable), fallback to NSE
    try:
        data = await yahoo.get_live(symbol)
        if data.get("price") is not None:
            return {"success": True, "data": data}
        raise Exception("No price from yahoo")
    except Exception as e:
        yahoo_err = str(e)
        # fallback to NSE (sync -> run in thread)
        try:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, lambda: nse.nse_live(symbol))
            return {"success": True, "data": data, "fallback": f"yahoo failed: {yahoo_err}"}
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"Both providers failed. Yahoo: {yahoo_err} | NSE: {str(e2)}")

@app.get("/api/history/{symbol}", tags=["Market data"], summary="OHLCV candles")
async def history(symbol: str, range: str = Query("1mo", alias="range"), interval: str = "1d"):
    # Normalize range/interval to yahoo valid
    range = range.lower()
    interval = interval.lower()
    
    try:
        data = await yahoo.get_history(symbol, range, interval)
        if data.get("candles"):
            return {"success": True, "data": data}
        raise Exception("Empty candles from yahoo")
    except Exception as e:
        yahoo_err = str(e)
        # NSE only supports daily - fallback if interval is 1d/1wk else fail
        if interval not in ("1d","1wk","1mo"):
            # for intraday fallback not possible, return yahoo error
            raise HTTPException(status_code=500, detail=f"Yahoo failed: {yahoo_err}. NSE fallback only supports 1d interval, requested {interval}")
        try:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, lambda: nse.nse_history(symbol, range))
            data["fallback_reason"] = f"yahoo failed: {yahoo_err}"
            return {"success": True, "data": data}
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"Both providers failed. Yahoo: {yahoo_err} | NSE: {str(e2)}")

@app.get("/api/screener/{symbol}", tags=["Market data"], summary="Fundamentals as markdown (Screener.in)", response_class=PlainTextResponse, responses={200: {"content": {"text/markdown": {}}}})
async def screener_data(symbol: str):
    """
    Screener.in fundamentals - **DIRECT MARKDOWN TEXT** (not JSON).

    Fetches https://www.screener.in/company/{symbol}/ and converts the rendered HTML
    directly to markdown via html-to-markdown converter (markdownify).
    
    Returns: `text/markdown` - pure markdown string with ALL sections:
    About, Key Metrics, Analysis (Pros/Cons), Peers, Quarters, Profit & Loss,
    Balance Sheet, Cash Flow, Ratios, Shareholding (Investors), Documents.
    
    No JSON wrapper - agent gets direct text for LLM prompt.
    Example: `GET /api/screener/VOGL` -> "# Vedanta Oil and Gas Ltd\n..."
    """
    try:
        md = await screener.get_screener_markdown(symbol)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8", headers={"X-Source": "screener.in", "Cache-Control": "public, max-age=60"})
    except Exception as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=500, detail=f"Screener fetch failed: {msg}")

# Additive analytics router; legacy routes above remain unchanged.
from app.analytics.routes import router as analytics_router
app.include_router(analytics_router)
from app.research.routes import router as research_router
app.include_router(research_router)
from app.home.routes import router as home_router, page as home_page, assets as home_assets
app.include_router(home_router)
from app.stock.routes import router as stock_router
app.include_router(stock_router)
app.mount('/static', home_assets, name='static')

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
