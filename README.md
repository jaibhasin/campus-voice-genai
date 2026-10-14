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

## Telephone calls with Twilio

Scout supports inbound calls and an explicit local command to call your configured mobile.
The backend, tunnel, and internet connection must remain running throughout a call.
The current Twilio trial docs block Media Streams, so verify streaming access on your older account or upgrade before a real test.
For calls to India, use a non-Indian Twilio caller number and enable India in Voice geographic permissions.
[Trial restrictions](https://www.twilio.com/docs/usage/trials/try-out-voice#blocked-verbs) and [India calling guidelines](https://www.twilio.com/en-us/guidelines/in/voice) describe these requirements.

Add the `TWILIO_*` values from `.env.example` to your ignored local `.env`.
Use E.164 numbers for `TWILIO_PHONE_NUMBER` and `TWILIO_ALLOWED_PHONE_NUMBER`, and set `TWILIO_ENABLED=true` once they are configured.
Only the configured mobile can call Scout or receive an outbound call.
Set `VOICE_INTERRUPTION_ENABLED=true` to enable contextual acknowledgments and interruptions on phone calls as well as browser calls.

Start the backend with one worker and without auto-reload:

```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal, start ngrok with the included policy, which exposes only the signed telephony endpoints:

```bash
ngrok http 8000 --traffic-policy-file ngrok-telephony.yml --inspect=false
```

Use ngrok's assigned HTTPS origin as `TWILIO_PUBLIC_BASE_URL`, then restart the backend before making calls.
Do not put a path, query string, or secret in that value.
Configure your Twilio number's incoming voice webhook as `https://<your-ngrok-domain>/api/telephony/voice`, method POST.
Dial the Twilio number from your permitted mobile for an inbound call.
International dialing charges from your carrier may apply.
For custom domains, Cloudflare named tunnels are also suitable; see [the phone integration plan](TWILIO_PHONE_PLAN.md).

To have Scout call your mobile, keep the backend and tunnel running and use a unique request ID:

```bash
uv run python -m backend.call_scout --request-id call-001
```

Repeating a successful request ID returns its original Call SID and does not redial.
The ignored `.state/phone-calls.sqlite3` file stores dialing intent before the API request, preventing duplicate calls after ambiguous timeouts or process crashes.
A new request is blocked while a previous outbound call is still active or its outcome is unknown.
Do not delete this file to recover from a timeout.
Check Twilio Console, then reconcile the unknown request with the matching Call SID:

```bash
uv run python -m backend.call_scout --resolve-request call-001 --call-sid CA...
```

If Console confirms that no call was created, use `--no-call-created` instead of `--call-sid`, then use a new request ID for the next attempt.
Outbound calls are limited to the configured destination, do not record audio, and never retry call creation automatically.
Call status callbacks reconcile inbound server state; the local command checks Twilio's live status before allowing another outbound request.

To verify the live speech providers without placing a telephone call:

```bash
uv run python -m backend.phone_probe
```

This synthesizes a short hostel-fee question and checks that Sarvam recognizes it through the same 8 kHz mu-law settings used for calls.
It prints sanitized stages and format/results, using a small amount of Sarvam API usage.
Phone input is retained for at most twenty seconds and synthesis output for at most ten seconds per packet.
Playback uses short marked segments with approximately 200 ms outstanding audio; a temporary pause can let that short tail finish before an acknowledgment resumes the answer.
Real interruptions clear buffered audio and cancel the owned answer.
Speech recognition startup is limited to twenty seconds, each speech-synthesis connection has a fifteen-second deadline, and calls are limited to `TWILIO_MAX_CALL_SECONDS` (600 by default).
Hangup, provider failure, deadline, and shutdown close the call session and remove its in-memory conversation checkpoints.

The implementation has deterministic Twilio protocol tests and a successful live Sarvam codec probe.
Actual Twilio/carrier calls, public signature validation through ngrok, and phone latency still require account configuration and real-call testing.

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
The selection applies to text chat and new voice calls, stays fixed during a reply or call, and starts at Normal LLM (GPT-6 Luna) on a page load.
Switching providers preserves the current conversation.
Chat and voice retain thread-scoped conversation context, with fresh source evidence for each question.
Retrieval is bounded by round, time, and request-size limits; incomplete retrieval is passed to the answer LLM as a limitation.
`RETRIEVAL_MAX_ROUNDS`, `RETRIEVAL_MAX_SECONDS`, and `RETRIEVAL_REQUEST_TIMEOUT` configure both providers; the legacy `JEV_*` limit variables remain supported.
Chat requests accept `retrieval_provider: "decisions" | "jev" | "llm_batch"`; omitted values default to `"decisions"` at the API boundary.
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
