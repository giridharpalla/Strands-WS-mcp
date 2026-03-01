"""
FastAPI REST API server for the Web Research Agent.

Endpoints:
  POST /ask        - Ask a question (stateless, new agent per request)
  POST /chat       - Chat with memory (session-based)
  POST /scrape     - Directly scrape a URL
  GET  /health     - Health check

Run:  uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from agent import WebResearchAgent, scrape_url

app = FastAPI(
    title="DiscOverflow Web Research Agent API",
    description="AI-powered web research agent using OpenAI + Strands Agents + MCP",
    version="1.0.0"
)

# --- Session store for chat mode ---
_sessions: dict[str, WebResearchAgent] = {}


# --- Request/Response models ---
class AskRequest(BaseModel):
    question: str

class ChatRequest(BaseModel):
    session_id: str
    question: str

class ScrapeRequest(BaseModel):
    url: str

class AgentResponse(BaseModel):
    answer: str
    total_time: float
    scrape_time: float
    llm_time: float

class ScrapeResponse(BaseModel):
    url: str
    content: str
    chars: int


# --- Endpoints ---

@app.get("/health")
def health():
    from agent import MODEL_ID
    return {"status": "ok", "model": MODEL_ID}


@app.post("/ask", response_model=AgentResponse)
def ask(req: AskRequest):
    """Ask a one-shot question (no conversation memory)."""
    try:
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        agent = WebResearchAgent()
        result = agent.ask(req.question)
        return AgentResponse(
            answer=result["answer"],
            total_time=round(result["total_time"], 2),
            scrape_time=round(result.get("scrape_time", 0.0), 2),
            llm_time=round(result.get("llm_time", 0.0), 2)
        )
    except Exception as e:
        import traceback
        return AgentResponse(
            answer=f"Server Exception: {str(e)}\n\n{traceback.format_exc()}",
            total_time=0.0,
            scrape_time=0.0,
            llm_time=0.0
        )


@app.post("/chat", response_model=AgentResponse)
def chat(req: ChatRequest):
    """Chat with conversation memory. Use the same session_id for follow-up questions."""
    if req.session_id not in _sessions:
        _sessions[req.session_id] = WebResearchAgent()

    agent = _sessions[req.session_id]
    result = agent.ask(req.question)
    return AgentResponse(
        answer=result["answer"],
        total_time=round(result["total_time"], 2),
        scrape_time=round(result["scrape_time"], 2),
        llm_time=round(result["llm_time"], 2)
    )


@app.post("/chat/{session_id}/reset")
def reset_chat(session_id: str):
    """Reset a chat session's conversation history."""
    if session_id in _sessions:
        _sessions[session_id].reset()
        return {"status": "reset", "session_id": session_id}
    raise HTTPException(status_code=404, detail="Session not found")


@app.post("/scrape", response_model=ScrapeResponse)
def scrape(req: ScrapeRequest):
    """Directly scrape a URL without AI analysis."""
    content = scrape_url(req.url)
    return ScrapeResponse(
        url=req.url,
        content=content,
        chars=len(content)
    )
