import asyncio
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from agent import WebResearchAgent, MODEL_ID, MCP_SERVER_URL

SCENARIOS = [
    "What mobile prepaid options are present in Barbados?",
    "What mobile postpaid plans are in Barbados?",
    "What are the home internet plans in Barbados?",
    "What mobile prepaid options are in Anguilla?",
    "What mobile postpaid plans are in Anguilla?",
    "Tell me about internet bundles in Anguilla.",
    "What are the prepaid plans in Antigua and Barbuda?",
    "What are the postpaid plans in Antigua and Barbuda?",
    "What internet bundles are available in Antigua?",
    "What are the prepaid mobile plans in the British Virgin Islands?",
    "What are the postpaid plans in British Virgin Islands?",
    "What internet bundles are available in British Virgin Islands?",
    "What are the Cayman Islands mobile prepaid plans?",
    "What are the Cayman Islands mobile postpaid plans?",
    "What home internet is available in Cayman Islands?",
    "What are the Grenada mobile prepaid plans?",
    "What are the Grenada mobile postpaid plans?",
    "What home internet bundles are in Grenada?",
    "What are the Turks and Caicos prepaid plans?",
    "What are the Turks and Caicos postpaid plans?",
    "What home internet options are in Turks and Caicos?",
    "What are the Jamaica mobile prepaid plans?",
    "What are the Jamaica mobile postpaid plans?",
    "What internet bundles are available in Jamaica?",
    "What are the Montserrat prepaid mobile plans?",
    "What are the Montserrat postpaid mobile plans?",
    "What internet bundles are available in Montserrat?",
    "What are the Saint Lucia prepaid mobile plans?",
    "What are the Saint Lucia postpaid mobile plans?",
    "What is the home internet in Saint Lucia like?"
]

def run_test(scenario_idx, query):
    agent = WebResearchAgent()
    start = time.time()
    try:
        scrapes = []
        def log_scrape(url, status, chars):
            if status == "start":
                scrapes.append(url)
                
        result = agent.ask(query, on_scrape=log_scrape)
        elapsed = time.time() - start
        answer = result.get("answer", "")
        
        status = "PASS"
        error_reason = ""
        
        if "API Error" in answer or "Error executing tool" in answer:
            status = "FAIL"
            error_reason = "Hit an API/Tool Error"
        elif len(answer) < 50:
            status = "FAIL"
            error_reason = f"Answer too short ({len(answer)} chars)"
        elif "I cannot Access" in answer or "I'm sorry" in answer or "an error occurred" in answer.lower():
            status = "FAIL"
            error_reason = "Agent apologized or failed to find info"
            
        return {
            "idx": scenario_idx,
            "query": query,
            "status": status,
            "error_reason": error_reason,
            "scrapes": len(scrapes),
            "answer_preview": answer[:150].replace('\n', ' ') + "...",
            "time": elapsed
        }
    except Exception as e:
        return {
            "idx": scenario_idx,
            "query": query,
            "status": "FAIL",
            "error_reason": f"Exception: {str(e)}",
            "scrapes": 0,
            "answer_preview": "",
            "time": time.time() - start
        }
    finally:
        try:
            agent.cleanup()
        except Exception:
            pass

def main():
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set.")
        return

    print("=" * 80)
    print("  CARIBBEAN RANDOM REGRESSION TEST SUITE (30 SCENARIOS)")
    print("=" * 80)
    print(f"Model ID:   {MODEL_ID}")
    print(f"MCP Server: {MCP_SERVER_URL}")
    print(f"Total Tests: {len(SCENARIOS)}")
    print("Running with 4 concurrent workers...\n")

    results = []
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(run_test, i+1, q): i for i, q in enumerate(SCENARIOS)}
        
        from concurrent.futures import as_completed
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            mark = "[OK]" if res["status"] == "PASS" else "[FAIL]"
            print(f"Test {res['idx']:02d} {mark} ({res['time']:.1f}s) | Scrapes: {res['scrapes']} | Q: {res['query'][:50]}...")

    results.sort(key=lambda x: x["idx"])
    
    print("\n" + "=" * 80)
    print("  REGRESSION TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = len(results) - passed
    
    for r in results:
        if r["status"] == "FAIL":
            print(f"[-] Test {r['idx']:02d} FAILED: {r['error_reason']}\n    Q: {r['query']}\n    A: {r['answer_preview']}\n")
            
    print(f"\nTotal Time: {time.time() - start_time:.1f}s")
    print(f"Pass Rate:  {passed}/{len(results)} ({(passed/len(results))*100:.1f}%)")
    print("ALL SCENARIOS PASSED!" if failed == 0 else "SOME TESTS FAILED.")
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    import asyncio
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    main()
