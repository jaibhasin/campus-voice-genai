"""
FastAPI backend for Scout — TIET College Assistant.

Initializes the Agent once on startup and exposes a streaming chat endpoint.

Run from project root:
    uvicorn backend.main:app --reload --port 8000
"""

import asyncio
import base64
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.tracers.langchain import wait_for_all_tracers
from pydantic import BaseModel, Field
from sarvamai import SarvamAI

# Ensure project root is on sys.path so `Agent` package is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Agent.graph import Agent
from Agent.prompts.prompts import voice_assistant_system_prompt

# ──────────────────────────────────────────────
#  Shared instances (created once on startup)
# ──────────────────────────────────────────────
agent_instance: Agent | None = None
voice_agent_instance: Agent | None = None
sarvam_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the agent and Sarvam client when the server starts."""
    global agent_instance, voice_agent_instance, sarvam_client

    print("[BOOT] Initializing Scout agent...")
    agent_instance = Agent(name="Scout")
    print("[BOOT] Chat agent ready!")

    print("[BOOT] Initializing Scout voice agent...")
    voice_agent_instance = Agent(
        name="Scout-Voice",
        system_prompt=voice_assistant_system_prompt,
    )
    print("[BOOT] Voice agent ready!")

    # Initialize Sarvam AI SDK client
    sarvam_key = os.getenv("SARVAM_API_KEY", "")
    if sarvam_key:
        try:
            
            sarvam_client = SarvamAI(api_subscription_key=sarvam_key)
            print("[BOOT] Sarvam AI client ready!")
        except Exception as e:  # noqa: BLE001 - Optional SDK startup must not disable chat.
            print(f"[BOOT] Sarvam AI init failed: {e}")
    else:
        print("[BOOT] SARVAM_API_KEY not set — voice features disabled")

    try:
        yield
    finally:
        print("[SHUTDOWN] Cleaning up...")
        try:
            await agent_instance.aclose()
            await voice_agent_instance.aclose()
        finally:
            # Drain buffered traces at shutdown, never on the response path.
            await asyncio.to_thread(wait_for_all_tracers)


# ──────────────────────────────────────────────
#  App
# ──────────────────────────────────────────────
app = FastAPI(
    title="Scout API",
    description="Backend API for the Scout TIET College Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins (public chatbot API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
#  Request models
# ──────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    thread_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    retrieval_provider: Literal["decisions", "jev"] = "decisions"


class TTSRequest(BaseModel):
    text: str
    language_code: str = "en-IN"
    speaker: str = "shubh"
    model: str = "bulbul:v3"


# ──────────────────────────────────────────────
#  Sarvam AI config (STT / TTS)
# ──────────────────────────────────────────────
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")


# ──────────────────────────────────────────────
#  Routes
# ──────────────────────────────────────────────
@app.get("/api/health")
@app.head("/api/health")
async def health():
    """Simple health check."""
    return {
        "status": "ok",
        "agent": agent_instance is not None,
        "sarvam": sarvam_client is not None,
        "name": "Scout API",
    }


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """
    Stream agent response as Server-Sent Events (SSE).

    The frontend sends a user message + thread_id.
    The agent retrieves local evidence through the selected decision provider, then streams
    the OpenRouter answer through LangGraph:

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
                config={"configurable": {
                    "thread_id": req.thread_id,
                    "retrieval_provider": req.retrieval_provider,
                }},
            ):
                data = json.dumps(event, ensure_ascii=False)
                yield f"data: {data}\n\n"
        except Exception as e:  # noqa: BLE001 - SSE boundary reports model failures to clients.
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


@app.post("/api/chat/voice")
async def chat_voice(req: ChatRequest):
    """
    Voice-optimized chat endpoint.

    Uses the same streaming pipeline as /api/chat but with a voice-tuned
    system prompt that produces short, spoken-language responses without
    markdown, emojis, tables, or [OPTIONS] blocks.
    """
    if voice_agent_instance is None:
        return {"error": "Voice agent not initialized"}

    def event_stream():
        try:
            for event in voice_agent_instance.stream(
                req.message,
                config={"configurable": {
                    "thread_id": req.thread_id,
                    "retrieval_provider": req.retrieval_provider,
                }},
            ):
                data = json.dumps(event, ensure_ascii=False)
                yield f"data: {data}\n\n"
        except Exception as e:  # noqa: BLE001 - SSE boundary reports model failures to clients.
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


# ──────────────────────────────────────────────
#  Sarvam AI — Speech-to-Text (SDK)
# ──────────────────────────────────────────────
@app.post("/api/stt")
async def speech_to_text(file: Annotated[UploadFile, File()]):
    """
    Transcribe audio using Sarvam AI SDK.

    Accepts a multipart audio file (WebM/WAV/MP3) from the browser's
    MediaRecorder and returns the transcribed text.
    """
    if sarvam_client is None:
        return {"error": "Sarvam AI not configured"}

    try:
        audio_bytes = await file.read()

        response = await asyncio.to_thread(
            sarvam_client.speech_to_text.transcribe,
            file=(file.filename or "audio.webm", audio_bytes, file.content_type),
            model="saaras:v3",
            mode="transcribe",
        )
        transcript = (
            response.transcript
            if hasattr(response, "transcript")
            else getattr(response, "text", str(response))
        )
        detected_lang = getattr(response, "language_code", None) or "en-IN"
        if detected_lang == "unknown":
            detected_lang = "en-IN"

        print(f"[STT Success] Transcript: {transcript} | Lang: {detected_lang}")

        return {"transcript": transcript, "language_code": detected_lang}

    except Exception as e:  # noqa: BLE001 - API boundary returns recoverable speech errors.
        print(f"[STT Error] {e}")
        return {"error": f"STT failed: {e!s}"}


# ──────────────────────────────────────────────
#  Sarvam AI — Text-to-Speech (SDK)
# ──────────────────────────────────────────────
@app.post("/api/tts")
async def text_to_speech(req: TTSRequest):
    """
    Convert text to speech using Sarvam AI SDK.

    Accepts a text string and returns base64-encoded audio.
    """
    if sarvam_client is None:
        return {"error": "Sarvam AI not configured"}

    try:
        clean_text = req.text[:2400] if req.text else ""
        if not clean_text:
            return {"error": "Empty text"}

        response = await asyncio.to_thread(
            sarvam_client.text_to_speech.convert,
            model="bulbul:v3",
            text=clean_text,
            language_code=req.language_code or "en-IN",
            speaker=req.speaker or "shubh",
            output_audio_codec="wav",
        )

        # SDK returns response with audios attribute (base64 strings)
        audio_b64 = ""
        if hasattr(response, "audios") and response.audios:
            audio_b64 = response.audios[0]
        elif hasattr(response, "audio"):
            # Some SDK versions return raw bytes
            audio_b64 = base64.b64encode(response.audio).decode("utf-8")

        return {"audio_base64": audio_b64}

    except Exception as e:  # noqa: BLE001 - API boundary returns recoverable speech errors.
        return {"error": f"TTS failed: {e!s}"}



@app.websocket("/api/voice/ws")
async def voice_websocket_endpoint(
    websocket: WebSocket,
    retrieval_provider: Literal["decisions", "jev"] = "decisions",
):
    from backend.voice_pipeline import voice_pipeline
    await voice_pipeline(websocket, voice_agent_instance, retrieval_provider)
