import asyncio
import time
from playwright.async_api import async_playwright, Page
from typing import Dict, Any

class DiscoverFlowScraper:
    def __init__(self):
        self._playwright = None
        self._browser = None
        self._cache = {}       # URL -> (timestamp, result)
        self._cache_ttl = 300  # Cache results for 5 minutes

    async def initialize(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def scrape(self, url: str) -> Dict[str, Any]:
        # Check cache first
        if url in self._cache:
            cached_time, cached_result = self._cache[url]
            if time.time() - cached_time < self._cache_ttl:
                return cached_result

        if not self._browser:
            await self.initialize()

        context = await self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            # Dismiss cookie banners / popups
            try:
                for selector in [
                    'button:has-text("Accept")', 'button:has-text("Accept All")',
                    'button:has-text("Got it")', 'button:has-text("OK")',
                    '[class*="cookie"] button', '[id*="cookie"] button',
                ]:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        await page.wait_for_timeout(1000)
                        break
            except Exception:
                pass

            # Scroll through the ENTIRE page to trigger lazy-loaded content
            await page.evaluate("""
                async () => {
                    const delay = ms => new Promise(r => setTimeout(r, ms));
                    const height = document.body.scrollHeight;
                    for (let i = 0; i < height; i += 600) {
                        window.scrollTo(0, i);
                        await delay(100);
                    }
                    window.scrollTo(0, 0);
                }
            """)
            await page.wait_for_timeout(1000)

            # Click through carousel/slider arrows to reveal ALL cards
            try:
                for arrow_sel in [
                    'button[class*="next"]', 'button[class*="slick-next"]',
                    '[class*="swiper-button-next"]', 'button[aria-label="Next"]',
                    '.next-arrow', '.carousel-control-next',
                ]:
                    arrows = page.locator(arrow_sel)
                    count = await arrows.count()
                    if count > 0:
                        for _ in range(10):  # click next up to 10 times to reveal all slides
                            try:
                                if await arrows.first.is_visible(timeout=500):
                                    await arrows.first.click()
                                    await page.wait_for_timeout(500)
                            except Exception:
                                break
                        break
            except Exception:
                pass

            title = await page.title()

            html_content = await page.content()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            # Remove scripts and styles
            for elements in soup(["script", "style", "noscript"]):
                elements.decompose()
            full_text = soup.get_text(separator=' ', strip=True)

            # Extract ALL links
            links = await page.evaluate("""() => {
                const anchors = Array.from(document.querySelectorAll('a'));
                return anchors
                    .map(a => ({ text: a.innerText.trim(), href: a.href }))
                    .filter(a => a.href && a.text && a.text.length < 200);
            }""")

            # Extract headings
            headings = await page.evaluate("""() => {
                const get = sel => Array.from(document.querySelectorAll(sel)).map(h => h.innerText.trim()).filter(Boolean);
                return { h1: get('h1'), h2: get('h2'), h3: get('h3') };
            }""")

            # Extract ALL structured content blocks (cards, sections, list items, etc.)
            # This is the KEY fix — we grab every distinct content section on the page
            structured_blocks = await page.evaluate("""() => {
                const blocks = [];
                const selectors = [
                    // Cards, plan containers, pricing boxes
                    '[class*="card"]', '[class*="Card"]',
                    '[class*="plan"]', '[class*="Plan"]',
                    '[class*="price"]', '[class*="Price"]',
                    '[class*="package"]', '[class*="Package"]',
                    '[class*="offer"]', '[class*="Offer"]',
                    '[class*="bundle"]', '[class*="Bundle"]',
                    '[class*="product"]', '[class*="Product"]',
                    '[class*="feature"]', '[class*="Feature"]',
                    '[class*="service"]', '[class*="Service"]',
                    // Slider/carousel items
                    '.slick-slide', '[class*="swiper-slide"]',
                    '[class*="carousel-item"]', '[class*="slide"]',
                    // Generic sections and list items
                    'article', 'section > div', 'li'
                ];
                
                const seen = new Set();
                for (const sel of selectors) {
                    const elements = document.querySelectorAll(sel);
                    for (const el of elements) {
                        const text = el.innerText ? el.innerText.trim() : (el.textContent ? el.textContent.trim() : '');
                        // Include meaningful blocks (not too short, not too long, not duplicates)
                        if (text && text.length > 15 && text.length < 2000 && !seen.has(text)) {
                            seen.add(text);
                            blocks.push(text);
                        }
                    }
                }
                return blocks;
            }""")

            result = {
                "url": url,
                "title": title,
                "headings": headings,
                "links": links[:30],
                "body_text": full_text[:8000],
                "structured_blocks": structured_blocks[:30],
                "status": "success"
            }
            # Cache the result
            self._cache[url] = (time.time(), result)
            return result

        except Exception as e:
            return {
                "url": url,
                "status": "error",
                "error": str(e)
            }
        finally:
            await context.close()

# Singleton instance for the app to use
scraper = DiscoverFlowScraper()
