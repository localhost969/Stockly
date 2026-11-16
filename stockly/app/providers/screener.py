import httpx
from bs4 import BeautifulSoup
import markdownify

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",  # no brotli decoder installed
    "Referer": "https://www.screener.in/",
    "Connection": "keep-alive",
}

def normalize_symbol(sym: str) -> str:
    return sym.strip().upper().replace(".NS","").replace(".BO","").replace(".NSE","")

async def fetch_html(symbol: str):
    sym = normalize_symbol(symbol)
    urls_to_try = [
        f"https://www.screener.in/company/{sym}/",
        f"https://www.screener.in/company/{sym}/consolidated/",
    ]
    async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
        for url in urls_to_try:
            r = await client.get(url)
            if r.status_code == 200 and "Company not found" not in r.text and len(r.text) > 5000:
                return r.text, url, sym
        # search fallback
        try:
            search_url = f"https://www.screener.in/api/company/search/?q={sym}"
            rs = await client.get(search_url)
            if rs.status_code == 200:
                j = rs.json()
                if j and len(j) > 0:
                    best = j[0]
                    url = best.get("url") or ""
                    if url:
                        if not url.startswith("http"):
                            url = "https://www.screener.in" + url
                        r2 = await client.get(url)
                        if r2.status_code == 200 and len(r2.text) > 5000:
                            return r2.text, url, sym
        except:
            pass
        raise Exception(f"Screener: Company '{sym}' not found (tried {urls_to_try})")

def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    # main container holds all sections
    main = soup.select_one("main.container")
    if not main:
        main = soup.select_one("main")
    if not main:
        main = soup.body
    if not main:
        raise Exception("No main content found")
    
    # Remove unwanted elements inside main that add noise but keep content
    for tag in main.select("script, style, noscript"):
        tag.decompose()
    
    # Convert to markdown via markdownify - preserves tables, headings, lists
    md = markdownify.markdownify(
        str(main),
        heading_style="ATX",
        bullets="-",
        strip=["script", "style"]
    )
    # Cleanup: collapse excessive blank lines (more than 2)
    import re
    md = re.sub(r"\n{3,}", "\n\n", md)
    # Fix encoding artifacts
    md = md.replace("\xa0", " ").replace("&nbsp;", " ")
    # Trim
    md = md.strip()
    # Add header with source url for context
    return md

async def get_screener_markdown(symbol: str):
    html, url, sym = await fetch_html(symbol)
    md = html_to_markdown(html)
    # Prepend title and source
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else sym
    company = soup.select_one("#top h1")
    company_name = company.get_text(strip=True) if company else sym
    header = f"# {company_name}\n\n> Source: {url}\n> {title}\n\n---\n\n"
    return header + md

# Keep old structured function for optional JSON use (not used now but kept)
async def get_screener_data(symbol: str):
    md = await get_screener_markdown(symbol)
    html, url, sym = await fetch_html(symbol)
    soup = BeautifulSoup(html, "lxml")
    company = soup.select_one("#top h1")
    company_name = company.get_text(strip=True) if company else sym
    return {
        "symbol": sym,
        "company_name": company_name,
        "url": url,
        "markdown": md
    }
