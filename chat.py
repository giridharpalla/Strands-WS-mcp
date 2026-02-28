"""
Interactive Chat CLI - powered by WebResearchAgent.

Type your questions about discoverflow.co (or any website) and the agent
will scrape live data to answer. Type 'quit' or 'exit' to stop.
"""

from agent import WebResearchAgent


def main():
    agent = WebResearchAgent()

    def log_scrape(url, status, chars):
        if status == "start":
            print(f"  [Scraping {url}...]")
        else:
            print(f"  [Done - {chars} chars]")

    print("=" * 60)
    print("  DiscOverflow Chat - Powered by Llama 4 Maverick")
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

        result = agent.ask(user_input, on_scrape=log_scrape)

        print(f"\nA: {result['answer']}")
        print(f"\n  [Latency: total={result['total_time']:.1f}s | "
              f"scraping={result['scrape_time']:.1f}s | "
              f"LLM={result['llm_time']:.1f}s]")


if __name__ == "__main__":
    main()
