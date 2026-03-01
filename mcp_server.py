"""
MCP Server for the DiscOverflow Web Scraper.

Runs the Playwright scraper as a persistent MCP (Model Context Protocol) server.
The browser stays warm between requests — no cold start penalty.

Usage:
  Local SSE mode:   python mcp_server.py
  Then connect from agent with: MCP_SERVER_URL=http://localhost:8080/sse

  Local stdio mode:  Can be used by MCP-compatible clients directly.
"""

import asyncio
import sys
import time
from mcp.server.fastmcp import FastMCP
from scraper import DiscoverFlowScraper

# --- Create MCP server ---
mcp = FastMCP("discoverflow-scraper", host="0.0.0.0", port=8080)

# --- Persistent scraper (warm browser) ---
_scraper: DiscoverFlowScraper | None = None
_cache: dict[str, tuple[float, dict]] = {}
_cache_ttl = 300  # 5 minutes


async def _get_scraper() -> DiscoverFlowScraper:
    """Get or create the persistent scraper instance."""
    global _scraper
    if _scraper is None:
        _scraper = DiscoverFlowScraper()
        await _scraper.initialize()
    return _scraper


def _format_data(data: dict) -> str:
    """Format scraped data into structured text."""
    if data["status"] == "error":
        return f"Error scraping: {data.get('error')}"

    result = f"URL: {data.get('url')}\nTitle: {data.get('title', 'N/A')}\n\n"

    result += "=== HEADINGS ===\n"
    for h in data.get("headings", {}).get("h1", []):
        result += f"  H1: {h}\n"
    for h in data.get("headings", {}).get("h2", []):
        result += f"  H2: {h}\n"
    for h in data.get("headings", {}).get("h3", []):
        result += f"  H3: {h}\n"

    blocks = data.get("structured_blocks", [])
    if blocks:
        result += "\n=== PAGE CONTENT BLOCKS (cards, plans, services, etc.) ===\n"
        for i, block in enumerate(blocks, 1):
            result += f"\n[Block {i}]\n{block}\n"

    result += "\n=== LINKS ===\n"
    for link in data.get("links", [])[:25]:
        text = link.get("text", "").strip()
        href = link.get("href", "").strip()
        if text and href:
            result += f"  - {text}: {href}\n"

    result += "\n=== FULL PAGE TEXT ===\n"
    result += data.get("body_text", "")[:8000]

    return result


# --- MCP Tool ---

@mcp.tool()
async def scrape_website(url: str) -> str:
    """
    Scrapes a dynamic JavaScript-rendered website using a headless browser.
    Returns the page title, headings, all structured content blocks
    (like cards, plans, products, services), links, and the full page text.
    Use this tool whenever you need to fetch real, current data from any website.

    Args:
        url: The URL to scrape, e.g. https://discoverflow.co/
    """
    # Check cache
    if url in _cache:
        cached_time, cached_data = _cache[url]
        if time.time() - cached_time < _cache_ttl:
            return _format_data(cached_data)

    scraper = await _get_scraper()
    data = await scraper.scrape(url)

    # Cache raw data
    if data["status"] == "success":
        _cache[url] = (time.time(), data)

    return _format_data(data)


# --- Pre-warm cache on startup ---

COUNTRIES = [
    "jamaica", "barbados", "anguilla", "antigua", 
    "british-virgin-islands", "cayman", "grenada", 
    "turks-and-caicos", "montserrat", "saint-lucia", 
    "dominica", "saint-vincent", "trinidad", "saint-kitts"
]

PREWARM_URLS = ["https://discoverflow.co/"]
for c in COUNTRIES:
    PREWARM_URLS.append(f"https://discoverflow.co/{c}/")
    PREWARM_URLS.append(f"https://discoverflow.co/{c}/mobile/plans/prepaid")
    PREWARM_URLS.append(f"https://discoverflow.co/{c}/mobile/plans/postpaid")
    PREWARM_URLS.append(f"https://discoverflow.co/{c}/internet-bundles")


async def prewarm_cache():
    """Scrape common pages on startup so first user query hits cache."""
    print(f"  Pre-warming cache for {len(PREWARM_URLS)} URLs...")
    scraper = await _get_scraper()
    
    # We will fetch 4 URLs concurrently to speed up startup drastically
    sem = asyncio.Semaphore(4)
    
    async def fetch(url):
        async with sem:
            try:
                # print(f"    Caching {url}...", end=" ", flush=True)
                data = await scraper.scrape(url)
                if data["status"] == "success":
                    _cache[url] = (time.time(), data)
                    print(f"    [OK] Cached {url} ({len(_format_data(data))} chars)")
                else:
                    print(f"    [SKIP] {url} ({data.get('error', 'unknown error')})")
            except Exception as e:
                print(f"    [ERROR] {url} ({e})")

    # Run them all concurrently
    await asyncio.gather(*(fetch(url) for url in PREWARM_URLS))    
    print(f"  Cache warm: {len(_cache)} URLs ready.\n")


# --- Entry point ---

if __name__ == "__main__":
    print("Starting DiscOverflow Scraper MCP Server...")
    print("  Transport: SSE")
    print("  Endpoint:  http://localhost:8080/sse")
    print("  Browser will stay warm between requests.\n")

    # Pre-warm the cache before starting the server.
    # Playwright requires ProactorEventLoop on Windows. We run pre-warm
    # in its own loop, then close it cleanly before starting the MCP server.
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(prewarm_cache())
        finally:
            # Close the scraper so Playwright resources are released with THIS loop
            if _scraper is not None:
                loop.run_until_complete(_scraper.close())
                _scraper = None
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
    except Exception as e:
        print(f"  Pre-warm failed (non-fatal): {e}")

    # Reset event loop policy and current loop so mcp.run() starts fresh.
    # The MCP server will create its own event loop internally.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    asyncio.set_event_loop(asyncio.new_event_loop())

    print("  Starting MCP server... Press Ctrl+C to stop.\n")
    mcp.run(transport="sse")


