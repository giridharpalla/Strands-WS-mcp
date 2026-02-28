"""
Reusable Web Research Agent powered by AWS Bedrock Llama 4 Maverick + Playwright.

This module provides the core WebResearchAgent class used by:
  - chat.py  (interactive CLI)
  - main.py  (FastAPI REST API)
"""

import json
import asyncio
import sys
import time
import boto3
from scraper import DiscoverFlowScraper

# --- Configuration ---
MODEL_ID = "us.meta.llama4-maverick-17b-instruct-v1:0"
REGION = "us-east-1"

# --- Bedrock Tool Schema ---
TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "scrape_website",
                "description": (
                    "Scrapes a dynamic JavaScript-rendered website using a headless browser. "
                    "Returns the page title, headings, all structured content blocks (like cards, "
                    "plans, products, services), links, and the full page text. "
                    "Use this tool whenever the user asks about any website content."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The URL to scrape, e.g. https://discoverflow.co/"
                            }
                        },
                        "required": ["url"]
                    }
                }
            }
        }
    ]
}

SYSTEM_PROMPT = [
    {
        "text": (
            "You are a knowledgeable web research assistant powered by a real-time web scraper. "
            "You have access to a scrape_website tool that fetches live content from any website "
            "using a headless browser.\n\n"
            "STRICT RULES:\n"
            "1. When the user asks about website content, ALWAYS use the scrape tool first.\n"
            "2. Answer ONLY based on actual scraped data. Never guess or make up information.\n"
            "3. The scraped data contains: HEADINGS, PAGE CONTENT BLOCKS (most important - "
            "contains plans, prices, products, cards, features), LINKS, and FULL PAGE TEXT. "
            "Read ALL sections carefully before answering.\n"
            "4. Give SPECIFIC details (prices, data amounts, features, names). Be thorough.\n"
            "5. NEVER tell the user to 'visit', 'check', or 'try' a URL themselves. "
            "YOU have the scraper tool. If you need more info from a different page, "
            "call the scrape_website tool again with that URL. You can call the tool "
            "multiple times in one response.\n"
            "6. If the first page you scrape doesn't have enough detail, look at the LINKS "
            "section to find a more specific page and scrape THAT page too. Keep scraping "
            "until you have a complete answer.\n"
            "7. The default website is https://discoverflow.co/. For country-specific pages, "
            "construct URLs like:\n"
            "   - https://discoverflow.co/en/web/st-maarten/mobile/plans/postpaid\n"
            "   - https://discoverflow.co/jamaica/mobile/plans/prepaid\n"
            "   - https://discoverflow.co/en/web/barbados/internet\n"
            "   - https://discoverflow.co/jamaica/internet-bundles\n"
            "8. Your answers must be COMPLETE and SELF-CONTAINED. The user must get the full "
            "answer from you without needing to do anything else."
        )
    }
]


# ─── URL Cache ───────────────────────────────────────────────────
_url_cache = {}
_cache_ttl = 300  # 5 minutes


def _format_scraped_data(data: dict) -> str:
    """Format raw scraper output into a structured string for the LLM."""
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


def scrape_url(url: str) -> str:
    """Scrape a URL and return formatted text. Uses a cache to avoid duplicate scrapes."""
    if url in _url_cache:
        cached_time, cached_result = _url_cache[url]
        if time.time() - cached_time < _cache_ttl:
            return cached_result

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    async def _run():
        s = DiscoverFlowScraper()
        await s.initialize()
        try:
            return await s.scrape(url)
        finally:
            await s.close()

    data = asyncio.run(_run())
    formatted = _format_scraped_data(data)
    _url_cache[url] = (time.time(), formatted)
    return formatted


# ─── Web Research Agent ──────────────────────────────────────────

class WebResearchAgent:
    """
    Stateful agent that uses AWS Bedrock Llama 4 Maverick + Playwright scraper.
    Maintains conversation history for multi-turn chats.
    """

    def __init__(self, model_id=MODEL_ID, region=REGION):
        self.client = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model_id
        self.messages = []

    def _handle_tool_calls(self, assistant_content):
        """Execute tool calls and return results with timing info."""
        tool_results = []
        total_scrape_time = 0.0

        for block in assistant_content:
            if "toolUse" in block:
                tool_use = block["toolUse"]
                tool_id = tool_use["toolUseId"]
                url = tool_use["input"].get("url", "https://discoverflow.co/")

                try:
                    scrape_start = time.time()
                    result_text = scrape_url(url)
                    elapsed = time.time() - scrape_start
                    total_scrape_time += elapsed

                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_id,
                            "content": [{"text": result_text}]
                        }
                    })
                except Exception as e:
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_id,
                            "content": [{"text": f"Error: {str(e)}"}],
                            "status": "error"
                        }
                    })

        return tool_results, total_scrape_time

    def ask(self, question: str, on_scrape=None) -> dict:
        """
        Send a question to the agent and get a response.

        Args:
            question: The user's question
            on_scrape: Optional callback(url, chars, seconds) for scrape events

        Returns:
            dict with keys: answer, total_time, scrape_time, llm_time
        """
        self.messages.append({
            "role": "user",
            "content": [{"text": question}]
        })

        start_time = time.time()
        total_scrape_time = 0.0
        total_llm_time = 0.0

        max_turns = 5
        for turn in range(max_turns):
            try:
                llm_start = time.time()
                response = self.client.converse(
                    modelId=self.model_id,
                    messages=self.messages,
                    system=SYSTEM_PROMPT,
                    toolConfig=TOOL_CONFIG,
                    inferenceConfig={"temperature": 0.1, "maxTokens": 4096}
                )
                total_llm_time += time.time() - llm_start
            except Exception as e:
                self.messages.pop()
                return {
                    "answer": f"API Error: {str(e)}",
                    "total_time": time.time() - start_time,
                    "scrape_time": total_scrape_time,
                    "llm_time": total_llm_time
                }

            stop_reason = response["stopReason"]
            output_message = response["output"]["message"]
            assistant_content = output_message["content"]
            self.messages.append(output_message)

            if stop_reason == "tool_use":
                # Execute scraper tool calls
                for block in assistant_content:
                    if "toolUse" in block:
                        url = block["toolUse"]["input"].get("url", "")
                        if on_scrape:
                            on_scrape(url, "start", 0)

                tool_results, scrape_elapsed = self._handle_tool_calls(assistant_content)
                total_scrape_time += scrape_elapsed

                # Report scrape completion
                for block in assistant_content:
                    if "toolUse" in block:
                        url = block["toolUse"]["input"].get("url", "")
                        cached = _url_cache.get(url)
                        chars = len(cached[1]) if cached else 0
                        if on_scrape:
                            on_scrape(url, "done", chars)

                self.messages.append({
                    "role": "user",
                    "content": tool_results
                })

            elif stop_reason == "end_turn":
                answer = ""
                for block in assistant_content:
                    if "text" in block:
                        answer += block["text"]

                return {
                    "answer": answer,
                    "total_time": time.time() - start_time,
                    "scrape_time": total_scrape_time,
                    "llm_time": total_llm_time
                }
            else:
                answer = ""
                for block in assistant_content:
                    if "text" in block:
                        answer += block["text"]
                return {
                    "answer": answer or f"Unexpected stop: {stop_reason}",
                    "total_time": time.time() - start_time,
                    "scrape_time": total_scrape_time,
                    "llm_time": total_llm_time
                }

        return {
            "answer": "Max tool-call turns reached without a final answer.",
            "total_time": time.time() - start_time,
            "scrape_time": total_scrape_time,
            "llm_time": total_llm_time
        }

    def reset(self):
        """Clear conversation history."""
        self.messages = []


# ─── One-shot mode ───────────────────────────────────────────────
if __name__ == "__main__":
    print("Starting one-shot agent...\n")
    agent = WebResearchAgent()

    def log_scrape(url, status, chars):
        if status == "start":
            print(f"  [Scraping {url}...]")
        else:
            print(f"  [Done - {chars} chars]")

    result = agent.ask(
        "Scrape https://discoverflow.co/ and provide a detailed summary of the website's "
        "main offerings, services, and available countries.",
        on_scrape=log_scrape
    )

    print(f"\n{'=' * 60}")
    print("RESULT")
    print(f"{'=' * 60}\n")
    print(result["answer"])
    print(f"\n[Latency: total={result['total_time']:.1f}s | scraping={result['scrape_time']:.1f}s | LLM={result['llm_time']:.1f}s]")
