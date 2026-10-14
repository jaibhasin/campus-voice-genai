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
The backend uses `OPENROUTER_API_KEY` for both OpenAI Decisions retrieval and final answers, and `SARVAM_API_KEY` for voice features.
Set `TYPESAFE_API_KEY` to enable the optional Jev retrieval provider and voice interruption classification.
Keep all provider keys on the server; never use `NEXT_PUBLIC_` variables for credentials.

## Voice interruptions

Set `VOICE_INTERRUPTION_ENABLED=true` in `.env` to classify speech that overlaps Scout's playback with Jev.
Scout continues the same answer for clear listening acknowledgments and gives the caller a turn for questions, corrections, confusion, or answers to Scout's questions.
Short inputs such as "no" and "what" are sent to Jev with conversation context.
Uncertain decisions and provider failures give the caller the floor.

Playback continues during overlapping speech, transcription, and classification until Jev accepts a caller turn.
VAD duration alone does not pause playback, so a sustained acknowledgment can preserve the answer without a gap.
Set `VOICE_INTERRUPTION_SPECULATIVE_PAUSE=true` to temporarily pause sustained caller speech after the grace period, retaining the remaining audio.
With that option enabled, an acknowledgment resumes the retained audio without restarting the answer, and microphone capture continues during a pause.
The default avoids speculative pauses, but Scout continues speaking while transcription and classification decide whether the caller wants a turn.
Canceled responses cannot send their remaining audio into a new response.
Jev infers whether the caller is answering a question from conversational context; question marks in generated text do not force a new turn.

`VOICE_INTERRUPTION_SPECULATIVE_PAUSE` defaults to false.
`VOICE_INTERRUPTION_GRACE_MS` defaults to 350 and applies only when speculative pauses are enabled.
`VOICE_INTERRUPTION_TIMEOUT_MS` defaults to 4000.
`VOICE_INTERRUPTION_TRANSCRIPT_TIMEOUT_MS` defaults to 1500 and recovers when speech ends without a transcript.
Recovery retains the original speech overlap so a delayed acknowledgment is still classified against the same response.
The feature defaults off for controlled enablement.
Deploy the frontend and backend together because voice calls require protocol version 2.

## Retrieval providers

OpenAI Decisions (`openai/gpt-6-luna-decisions` through OpenRouter's `POST /api/alpha/decisions`) navigates local PageIndex documents and selects source text by default; the answer LLM responds using that evidence.
Use the compact dropdown below Call Scout to select Decisions, Jev, or Normal LLM (GPT-6 Luna).
The selection applies to text chat and new voice calls, stays fixed during a reply or call, and resets to Decisions on a page refresh.
Switching providers preserves the current conversation.
Chat and voice retain thread-scoped conversation context, with fresh source evidence for each question.
Retrieval is bounded by round, time, and request-size limits; incomplete retrieval is passed to the answer LLM as a limitation.
`RETRIEVAL_MAX_ROUNDS`, `RETRIEVAL_MAX_SECONDS`, and `RETRIEVAL_REQUEST_TIMEOUT` configure both providers; the legacy `JEV_*` limit variables remain supported.
Chat requests accept `retrieval_provider: "decisions" | "jev" | "llm_batch"`, defaulting to `"decisions"`.
The voice WebSocket accepts the same values in its `retrieval_provider` query parameter.
Unavailable providers report incomplete retrieval rather than silently switching providers.
For standalone agents, `RETRIEVAL_MODE=jev` selects Jev and `RETRIEVAL_MODE=llm` keeps the original LLM tool-selection baseline.

Normal LLM uses the same `openai/gpt-6-luna` model through OpenRouter to choose between a streaming `reply` and a `read_pageindex` source batch.
Greetings and clarifications can use one model call.
Factual questions normally use two calls to Luna: select sources, then answer using their actual text.
The first call sees a cached catalog and can select up to six source nodes across three branches at any depth, without opening every parent separately.
The strict tool schema has one shared `source_ids` list capped at six, containing only actual unread source IDs.
The backend derives document branches from those sources, reads at most three documents per batch, and reports extra-document sources as omitted.
If evidence is missing, one further batch is allowed before a final Luna call forced to `reply`.
Source IDs and prior reads are validated before the entire batch executes, and duplicate IDs within a batch are read once.
Whole source chunks are retained under a shared evidence allowance; omitted chunks are reported to the model as incomplete evidence.
Query arguments and prose accompanying tool calls are never sent to TTS.
Luna must choose exactly one tool per response, with parallel tool calls disabled and strict schemas enabled.
Decoded `reply.text` streams into chat and the voice sentence queue as it arrives, including greetings and answers after the first source batch.
TTS receives each complete sentence while Luna can continue generating later sentences.

Use `RETRIEVAL_MODE=llm_batch` to make this mode the standalone agent default.
`NORMAL_LLM_REQUEST_TIMEOUT`, `NORMAL_LLM_MAX_SECONDS`, and `NORMAL_LLM_EVIDENCE_BYTES` default to 15 seconds per model call, 45 seconds per turn, and 32,000 bytes of source evidence.
The catalog is bounded to 96,000 bytes and total requests to 160,000 bytes.
An oversized catalog fails explicitly rather than silently omitting documents.
This mode uses bounded recent conversation and any existing summary without invoking the separate summarizer.
The optional Jev voice interruption classifier remains separate from Luna's answering and source selection.
Compare observed latency and source coverage before changing the default; fewer requests alone do not prove faster replies.

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
uv run python -m unittest Agent.test_documents Agent.test_decisions Agent.test_retrieval Agent.test_graph Agent.test_tracing backend.test_voice_language backend.test_voice_activity backend.test_voice_pipeline backend.test_voice_interruption backend.test_voice_response backend.test_agent_endpoints -v
```

Run deterministic browser playback lifecycle tests with:

```bash
node --test frontend/src/lib/voicePlayback.test.mjs
```

Tests mock model providers and API calls; use configured API keys to separately evaluate live answer quality, latency, and cost on representative questions.
