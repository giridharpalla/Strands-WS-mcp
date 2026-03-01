"""
Interactive Chat CLI with STREAMING responses.

Words appear in real-time as the LLM generates them, dramatically
reducing perceived latency. Type 'quit' or 'exit' to stop.

Usage:
  Direct mode:    python chat.py
  MCP mode:       set MCP_SERVER_URL=http://localhost:8080/sse && python chat.py
  Custom model:   set OPENAI_MODEL=gpt-4o && python chat.py
"""

import sys
from agent import WebResearchAgent, MCP_SERVER_URL, MODEL_ID


def main():
    agent = WebResearchAgent()

    print("=" * 60)
    print(f"  DiscOverflow Chat - Powered by {MODEL_ID}")
    if MCP_SERVER_URL:
        print(f"  Scraper: MCP Server ({MCP_SERVER_URL})")
    else:
        print("  Scraper: Error - MCP_SERVER_URL not set")
    print("  Streaming: ON (real-time word-by-word output)")
    print("  Ask me anything about discoverflow.co!")
    print("  Type 'quit' or 'exit' to stop.")
    print("=" * 60)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        # Stream the response
        print("\nA: ", end="", flush=True)
        for event in agent.ask_stream(user_input):
            if event["type"] == "text":
                print(event["token"], end="", flush=True)

            elif event["type"] == "scrape_start":
                print(f"\n  [Scraping {event['url']}...]", flush=True)

            elif event["type"] == "scrape_done":
                print(f"  [Done - {event['chars']} chars]", flush=True)
                print("  ", end="", flush=True)

            elif event["type"] == "done":
                t = event["total_time"]
                s = event["scrape_time"]
                l = event["llm_time"]
                print(f"\n\n  [Latency: total={t:.1f}s | scraping={s:.1f}s | LLM={l:.1f}s]")

            elif event["type"] == "error":
                print(f"\n  [Error: {event['message']}]")

    # Clean up agent resources to avoid garbage collection exceptions on shutdown
    try:
        agent.cleanup()
    except Exception:
        pass


if __name__ == "__main__":
    main()
