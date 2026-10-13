# TIET Chat Bot

## Run the frontend

From the project root:

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:3000`.

## Run the backend

From the project root, create the uv environment and install the Python dependencies:

```bash
uv venv
uv pip install -r requirements.txt
```

Start the FastAPI backend in a separate terminal:

```bash
uv run uvicorn backend.main:app --reload --port 8000
```

The backend runs at `http://localhost:8000`.

Voice answers and speech use the accepted conversation language; the agent preserves it across uncertain detections and follow-ups, and checks in after 60 seconds of inactivity.

## Environment variables

Copy `.env.example` to `.env` in the project root and fill in your keys.
The backend uses `TYPESAFE_API_KEY` for Jev retrieval, `OPENROUTER_API_KEY` for final answers, and `SARVAM_API_KEY` for voice features.

## Voice interruptions

Set `VOICE_INTERRUPTION_ENABLED=true` in `.env` to classify speech that overlaps Scout's playback with Jev.
Scout continues the same answer for clear listening acknowledgments and gives the caller a turn for questions, corrections, confusion, or answers to Scout's questions.
Short inputs such as "no" and "what" are sent to Jev with conversation context.
Uncertain decisions and provider failures give the caller the floor.

Playback continues for a configurable grace period before temporarily pausing while speech or classification remains pending.
An acknowledgment resumes the retained audio without restarting the answer, and microphone capture continues during a pause.
Canceled responses cannot send their remaining audio into a new response.

`VOICE_INTERRUPTION_GRACE_MS` defaults to 350 and `VOICE_INTERRUPTION_TIMEOUT_MS` defaults to 1000.
`VOICE_INTERRUPTION_TRANSCRIPT_TIMEOUT_MS` defaults to 1500 and recovers when speech ends without a transcript.
The feature defaults off for controlled enablement.
Deploy the frontend and backend together because voice calls require protocol version 2.

## Jev retrieval

Jev navigates local PageIndex documents and selects source text; the answer LLM responds using that evidence.
Chat and voice share thread-scoped conversation summaries and recent history, with fresh retrieval for each question.
Retrieval is bounded by round, time, and request-size limits; incomplete retrieval is passed to the answer LLM as a limitation.
Set `RETRIEVAL_MODE=llm` to compare with the original LLM tool-selection flow.

## LangSmith

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env`; `LANGSMITH_PROJECT` is optional.
Traces follow decisions, retrieved sources, and answer generation, recording evidence, timing, usage, and errors while excluding credentials and client objects.
Traces are grouped by `thread_id` and flushed at shutdown; they show observable activity, not internal reasoning.

## Continuous improvement priorities

- Regularly review traces to see which data and model settings shape answers and where the system fails.
- Build a reliable system to check every PDF on Thapar's official website and update the knowledge base when PDFs change.
- Regularly review and improve each model's system prompt to improve answer quality.

## Verification

Run the unit suite with:

```bash
uv run python -m unittest Agent.test_documents Agent.test_retrieval Agent.test_graph Agent.test_tracing backend.test_voice_language backend.test_voice_activity backend.test_voice_pipeline backend.test_voice_interruption backend.test_voice_response backend.test_agent_endpoints -v
```

Run deterministic browser playback lifecycle tests with:

```bash
node --test frontend/src/lib/voicePlayback.test.mjs
```

Tests mock model providers and API calls; use configured API keys to separately evaluate live answer quality, latency, and cost on representative questions.
