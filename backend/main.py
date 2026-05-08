"""
FastAPI backend for Scout — TIET College Assistant.

Initializes the Agent once on startup and exposes a streaming chat endpoint.

Run from project root:
    uvicorn backend.main:app --reload --port 8000
"""

import sys
import json
import uuid
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Ensure project root is on sys.path so `Agent` package is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Agent.graph import Agent


# ──────────────────────────────────────────────
#  Shared agent instance (created once on startup)
# ──────────────────────────────────────────────
agent_instance: Agent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the agent when the server starts."""
    global agent_instance
    print("[BOOT] Initializing Scout agent...")
    agent_instance = Agent(name="Scout")
    print("[BOOT] Agent ready!")
    yield
    print("[SHUTDOWN] Cleaning up...")


# ──────────────────────────────────────────────
#  App
# ──────────────────────────────────────────────
app = FastAPI(
    title="Scout API",
    description="Backend API for the Scout TIET College Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Next.js dev server and production origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
#  Request model
# ──────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    thread_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


# ──────────────────────────────────────────────
#  Routes
# ──────────────────────────────────────────────
@app.get("/api/health")
async def health():
    """Simple health check."""
    return {
        "status": "ok",
        "agent": agent_instance is not None,
        "name": "Scout API",
    }


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """
    Stream agent response as Server-Sent Events (SSE).

    The frontend sends a user message + thread_id.
    The agent processes it through the LangGraph pipeline (with tool calling
    via OpenRouter API) and streams back events:

    Event types:
        - token:     { "type": "token",     "content": "..." }
        - tool_call: { "type": "tool_call", "name": "...", "args": "..." }
        - done:      { "type": "done",      "full_content": "...", "tool_calls": [...] }
        - error:     { "type": "error",     "message": "..." }
    """
    if agent_instance is None:
        return {"error": "Agent not initialized"}

    def event_stream():
        try:
            for event in agent_instance.stream(
                req.message,
                config={"configurable": {"thread_id": req.thread_id}},
            ):
                data = json.dumps(event, ensure_ascii=False)
                yield f"data: {data}\n\n"
        except Exception as e:
            error_event = json.dumps({
                "type": "error",
                "message": str(e),
            })
            yield f"data: {error_event}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
