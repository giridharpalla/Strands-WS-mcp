import os
import sys
import time
import asyncio
import queue
import threading

from strands import Agent
from strands.models.openai import OpenAIModel
from strands.tools.mcp import MCPClient
from strands.handlers.callback_handler import null_callback_handler
from strands.hooks.events import BeforeToolCallEvent, AfterToolCallEvent
from mcp.client.sse import sse_client

# --- Configuration ---
MODEL_ID = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8080/sse")

SYSTEM_PROMPT = (
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
    "7. The default website is https://discoverflow.co/. If the user asks about a specific country, "
    "we have pre-cached specific pages for zero-latency scraping. FIRST scrape the country's main page "
    "(e.g., https://discoverflow.co/jamaica/, https://discoverflow.co/barbados/). "
    "THEN, automatically scrape the specific sub-pages if you need them, as they are instantly available: "
    "  - https://discoverflow.co/<country>/mobile/plans/prepaid "
    "  - https://discoverflow.co/<country>/mobile/plans/postpaid "
    "  - https://discoverflow.co/<country>/internet-bundles "
    "Do NOT guess other URL structures blindly. Always check the 'LINKS' section in the scraped result if you "
    "need an exact URL that isn't one of the standard ones above.\n"
    "8. Your answers must be COMPLETE and SELF-CONTAINED. The user must get the full "
    "answer from you without needing to do anything else.\n"
    "9. CRITICAL ANTI-LOOP RULE: Do NOT scrape the exact same URL more than once in a single message. "
    "If you scrape a URL and it does not contain the information you need, do NOT scrape it again. \n"
    "10. If you have scraped 3 different pages and still cannot find the specific plans or prices requested, "
    "STOP scraping and inform the user that the specific details are currently unavailable on the website."
)

# if sys.platform == "win32":
#     asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

class WebResearchAgent:
    """
    Stateful agent using Strands Agents + OpenAI + MCP.
    Supports both non-streaming (.ask) and streaming (.ask_stream) modes.
    """

    def __init__(self, model_id=None):
        self.model_id = model_id or MODEL_ID
        self.model = OpenAIModel(model_id=self.model_id)

        self.tools = []
        self.mcp_client = None
        if MCP_SERVER_URL:
            # MCP Client expects a callable that returns an async context manager
            # sse_client satisfies this contract.
            self.mcp_client = MCPClient(lambda: sse_client(MCP_SERVER_URL))
            self.tools.append(self.mcp_client)

        self.agent = Agent(
            model=self.model,
            tools=self.tools,
            system_prompt=SYSTEM_PROMPT,
            callback_handler=null_callback_handler
        )

        self.total_scrape_time = 0.0
        self._scrape_start_time = 0.0
        self._current_url = ""
        self._on_scrape = None
        self._streaming_events = queue.Queue()

        # Add hooks to measure latencies
        self.agent.add_hook(self.on_before_tool, BeforeToolCallEvent)
        self.agent.add_hook(self.on_after_tool, AfterToolCallEvent)

    def on_before_tool(self, event: BeforeToolCallEvent):
        self._scrape_start_time = time.time()
        self._current_url = event.tool_use.get("input", {}).get("url", "unknown url")
        if self._on_scrape:
            self._on_scrape(self._current_url, "start", 0)
        self._streaming_events.put({"type": "scrape_start", "url": self._current_url})

    def on_after_tool(self, event: AfterToolCallEvent):
        elapsed = 0.0
        if self._scrape_start_time > 0:
            elapsed = time.time() - self._scrape_start_time
            self.total_scrape_time += elapsed
            self._scrape_start_time = 0.0
            
        chars = 0
        if event.result and "content" in event.result:
            for item in event.result["content"]:
                if "text" in item:
                    chars += len(item["text"])
        
        if self._on_scrape:
            self._on_scrape(self._current_url, "done", chars)
        self._streaming_events.put({"type": "scrape_done", "url": self._current_url, "chars": chars})

    def reset(self):
        """Clear conversation history."""
        self.agent.messages.clear()

    def ask(self, question: str, on_scrape=None) -> dict:
        """Non-streaming query. Returns full answer at once."""
        self.total_scrape_time = 0.0
        self._on_scrape = on_scrape
        with self._streaming_events.mutex:
            self._streaming_events.queue.clear()
        
        start_time = time.time()
        try:
            # First, check if there's already an active event loop.
            # If so, run the async function in it directly. Otherwise, use asyncio.run
            try:
                loop = asyncio.get_running_loop()
                result = loop.run_until_complete(self.agent.invoke_async(question))
            except RuntimeError:
                result = asyncio.run(self.agent.invoke_async(question))
        except Exception as e:
            total_time = time.time() - start_time
            llm_time = total_time - self.total_scrape_time
            return {
                "answer": f"API Error: {str(e)}",
                "total_time": total_time,
                "scrape_time": self.total_scrape_time,
                "llm_time": llm_time
            }

        total_time = time.time() - start_time
        llm_time = max(0, total_time - self.total_scrape_time)
        
        # Get final text out of agent messages
        answer = ""
        if result and hasattr(result, "message") and result.message:
            for item in result.message.get("content", []):
                if hasattr(item, "text"):
                    answer += item.text
                elif isinstance(item, dict) and "text" in item:
                    answer += item["text"]
                    
        return {
            "answer": answer,
            "total_time": total_time,
            "scrape_time": self.total_scrape_time,
            "llm_time": llm_time
        }

    def ask_stream(self, question: str):
        """Streaming query utilizing a background thread to bridge async callbacks."""
        self.total_scrape_time = 0.0
        self._on_scrape = None
        with self._streaming_events.mutex:
            self._streaming_events.queue.clear()
        
        start_time = time.time()
        q = queue.Queue()
        done_marker = object()

        def background_stream():
            try:
                # Setup proper event loop for this thread to run strands Agents
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def runner():
                    async for evt in self.agent.stream_async(question):
                        q.put(evt)
                
                loop.run_until_complete(runner())
            except Exception as e:
                q.put({"type": "error", "message": str(e)})
            finally:
                q.put(done_marker)
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                loop.close()

        t = threading.Thread(target=background_stream, daemon=True)
        t.start()

        while True:
            # Drain any hook events first
            while not self._streaming_events.empty():
                yield self._streaming_events.get()

            # Wait for next token/event with timeout so we can still flush hook events periodically
            try:
                evt = q.get(timeout=0.1)
                if evt is done_marker:
                    break
                
                if isinstance(evt, dict):
                    if evt.get("type") == "error":
                        yield evt
                    else:
                        text = evt.get("data", "")
                        if text:
                            yield {"type": "text", "token": text}
            except queue.Empty:
                pass 

        # Final drain of hook events
        while not self._streaming_events.empty():
            yield self._streaming_events.get()

        t.join()
        total_time = time.time() - start_time
        llm_time = max(0, total_time - self.total_scrape_time)
        yield {
            "type": "done",
            "total_time": total_time,
            "scrape_time": self.total_scrape_time,
            "llm_time": llm_time
        }

    def cleanup(self):
        """Explicitly cleanup resources, especially the MCP client event loop."""
        if hasattr(self.agent, "cleanup"):
            try:
                self.agent.cleanup()
            except Exception:
                pass

def scrape_url(url: str) -> str:
    """Standalone fallback for main.py /scrape endpoint."""
    if not MCP_SERVER_URL:
        return "MCP_SERVER_URL not set."
        
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    
    async def _run():
        async with sse_client(MCP_SERVER_URL) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("scrape_website", {"url": url})
                text_parts = []
                for content in result.content:
                    if hasattr(content, "text"):
                        text_parts.append(content.text)
                return "\n".join(text_parts)
                
    return asyncio.run(_run())


# ─── One-shot mode ───────────────────────────────────────────────
if __name__ == "__main__":
    print("Starting one-shot agent...\n")
    print(f"  Model: {MODEL_ID}")
    print(f"  Scraper mode: {'MCP (' + MCP_SERVER_URL + ')' if MCP_SERVER_URL else 'Error - MCP_SERVER_URL not set'}\n")

    agent_instance = WebResearchAgent()

    def log_scrape(url, status, chars):
        if status == "start":
            print(f"  [Scraping {url}...]")
        else:
            print(f"  [Done - {chars} chars]")

    result = agent_instance.ask(
        "Scrape https://discoverflow.co/ and provide a detailed summary of the website's "
        "main offerings, services, and available countries.",
        on_scrape=log_scrape
    )

    print(f"\n{'=' * 60}")
    print("RESULT")
    print(f"{'=' * 60}\n")
    print(result.get("answer", "No answer"))
    print(f"\n[Latency: total={result.get('total_time', 0):.1f}s | scraping={result.get('scrape_time', 0):.1f}s | LLM={result.get('llm_time', 0):.1f}s]")

    # Clean up agent resources to avoid GC shutdown exceptions
    try:
        agent_instance.cleanup()
    except Exception:
        pass

