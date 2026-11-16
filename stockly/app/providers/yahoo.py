import httpx
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",  # no brotli decoder installed
    "Referer": "https://finance.yahoo.com/",
    "Origin": "https://finance.yahoo.com",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

# Yahoo allowed values
VALID_RANGES = {"1d","5d","1mo","3mo","6mo","1y","2y","5y","10y","ytd","max"}
VALID_INTERVALS = {"1m","2m","5m","15m","30m","60m","90m","1h","1d","5d","1wk","1mo","3mo"}

def normalize_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if "." in s:
        return s
    # default to NSE
    return f"{s}.NS"

async def fetch_chart(symbol: str, range_: str = "1mo", interval: str = "1d"):
    sym = normalize_symbol(symbol)
    
    if range_ not in VALID_RANGES:
        range_ = "1mo"
    if interval not in VALID_INTERVALS:
        interval = "1d"

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    params = {
        "range": range_,
        "interval": interval,
        "includePrePost": "false",
        "events": "div%7Csplit",
        "corsDomain": "finance.yahoo.com"
    }
    async with httpx.AsyncClient(headers=HEADERS, timeout=10, follow_redirects=True) as client:
        r = await client.get(url, params=params)
        # fallback to query2 if 429/404
        if r.status_code != 200:
            url2 = f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
            r = await client.get(url2, params=params)
        r.raise_for_status()
        data = r.json()
        
        result = data.get("chart", {}).get("result")
        if not result:
            err = data.get("chart", {}).get("error")
            raise Exception(f"Yahoo error: {err}")
        return result[0]

async def get_history(symbol: str, range_: str, interval: str):
    raw = await fetch_chart(symbol, range_, interval)
    meta = raw.get("meta", {})
    timestamps = raw.get("timestamp", []) or []
    quote = raw.get("indicators", {}).get("quote", [{}])[0]
    adjclose = raw.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])

    candles = []
    for i, ts in enumerate(timestamps):
        try:
            candles.append({
                "date": ts,
                "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts)),
                "open": quote.get("open", [None])[i],
                "high": quote.get("high", [None])[i],
                "low": quote.get("low", [None])[i],
                "close": quote.get("close", [None])[i],
                "adjClose": adjclose[i] if i < len(adjclose) else None,
                "volume": quote.get("volume", [None])[i],
            })
        except:
            continue

    return {
        "source": "yahoo",
        "symbol": symbol.upper(),
        "yahoo_symbol": normalize_symbol(symbol),
        "meta": {
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
            "instrumentType": meta.get("instrumentType"),
            "regularMarketPrice": meta.get("regularMarketPrice"),
            "previousClose": meta.get("previousClose") or meta.get("chartPreviousClose"),
            "regularMarketTime": meta.get("regularMarketTime"),
        },
        "range": range_,
        "interval": meta.get("dataGranularity") or interval,   # what Yahoo actually returned
        "candles": candles
    }

async def get_live(symbol: str):
    # use 1d 1m to get live price
    raw = await fetch_chart(symbol, "1d", "1m")
    meta = raw.get("meta", {})
    # last candle close is live-ish
    timestamps = raw.get("timestamp", []) or []
    quote = raw.get("indicators", {}).get("quote", [{}])[0]
    
    last = None
    if timestamps and quote.get("close"):
        # find last non-null close
        for i in reversed(range(len(timestamps))):
            c = quote["close"][i]
            if c is not None:
                last = {
                    "price": c,
                    "open": quote["open"][i],
                    "high": quote["high"][i],
                    "low": quote["low"][i],
                    "volume": quote["volume"][i],
                    "timestamp": timestamps[i]
                }
                break
    
    return {
        "source": "yahoo",
        "symbol": symbol.upper(),
        "yahoo_symbol": normalize_symbol(symbol),
        "price": meta.get("regularMarketPrice") or (last["price"] if last else None),
        "previousClose": meta.get("previousClose") or meta.get("chartPreviousClose"),
        "open": meta.get("regularMarketPrice") and meta.get("regularMarketPrice") or (last["open"] if last else None),
        "dayHigh": meta.get("regularMarketDayHigh"),
        "dayLow": meta.get("regularMarketDayLow"),
        "currency": meta.get("currency"),
        "exchange": meta.get("exchangeName"),
        "marketTime": meta.get("regularMarketTime"),
        "lastCandle": last
    }
