# Campus Voice

Campus Voice is an AI-powered campus assistant for Thapar Institute of Engineering & Technology (TIET) that answers student queries about admissions, fees, hostel allocation, programmes, and more. It supports both text chat and voice conversations, using retrieval-augmented generation over official TIET documents to give accurate, source-grounded answers.

---

## Table of Contents

- [Run the frontend](#run-the-frontend)
- [Run the backend](#run-the-backend)
- [Environment variables](#environment-variables)
- [Telephone calls with Twilio](#telephone-calls-with-twilio)
- [Voice interruptions](#voice-interruptions)
- [Retrieval providers](#retrieval-providers)
- [LangSmith tracing](#langsmith)
- [Running tests](#verification)

---

## Run the frontend

From the project root:

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:3000`.

---

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

Voice answers and speech use the accepted conversation language. The agent preserves the detected language across uncertain detections and follow-ups, and checks in after 60 seconds of inactivity.

---

## Environment variables

Copy `.env.example` to `.env` in the project root and fill in your keys.

- `OPENROUTER_API_KEY` — used for retrieval and final answers via OpenRouter.
- `SARVAM_API_KEY` — optional; enables voice (speech-to-text and text-to-speech) features.
- `TYPESAFE_API_KEY` — optional; enables the Jev retrieval provider and voice interruption classification.

Keep all provider keys on the server side. Never use `NEXT_PUBLIC_` variables for credentials.

---

## Telephone calls with Twilio

Scout (the voice assistant) supports inbound calls and an explicit local command to call your configured mobile. The backend, tunnel, and internet connection must remain running throughout a call.

> **Note:** The current Twilio trial blocks Media Streams. Verify streaming access on your account or upgrade before testing.
> For calls to India, use a non-Indian Twilio caller number and enable India in Voice geographic permissions.

Add the `TWILIO_*` values from `.env.example` to your local `.env`.

- Use E.164 format for `TWILIO_PHONE_NUMBER` and `TWILIO_ALLOWED_PHONE_NUMBER`.
- Set `TWILIO_ENABLED=true` once the numbers are configured.
- Only the configured mobile can call Scout or receive an outbound call.
- Phone calls default to Normal LLM (GPT-6 Luna), with spoken replies streamed sentence by sentence.
- Set `TWILIO_RETRIEVAL_PROVIDER=decisions` or `jev` to choose another provider.
- Set `VOICE_INTERRUPTION_ENABLED=true` to enable contextual acknowledgments and interruptions on phone calls as well as browser calls.

Start the backend with one worker and without auto-reload:

```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal, start ngrok with the included policy (exposes only signed telephony endpoints):

```bash
ngrok http 8000 --traffic-policy-file ngrok-telephony.yml --inspect=false
```

Use ngrok's assigned HTTPS origin as `TWILIO_PUBLIC_BASE_URL`, then restart the backend before making calls. Configure your Twilio number's incoming voice webhook as:

```
https://<your-ngrok-domain>/api/telephony/voice  (POST)
```

Dial the Twilio number from your permitted mobile for an inbound call.

**To have Scout call your mobile**, keep the backend and tunnel running and use a unique request ID:

```bash
uv run python -m backend.call_scout --request-id call-001
```

Repeating a successful request ID returns its original Call SID and does not redial. A new request is blocked while a previous outbound call is still active.

If a call attempt results in an unknown outcome, reconcile it using the Twilio Console and:

```bash
# If a call was created:
uv run python -m backend.call_scout --resolve-request call-001 --call-sid CA...

# If no call was created:
uv run python -m backend.call_scout --resolve-request call-001 --no-call-created
```

Then use a new request ID for the next attempt.

**To verify live speech providers without placing a real call:**

```bash
uv run python -m backend.phone_probe
```

This synthesizes a short question and checks that Sarvam recognizes it through the same 8 kHz mu-law settings used for calls.

**Key phone call limits:**
- Speech recognition startup: 20 seconds max
- Each speech-synthesis connection: 15-second deadline
- Max call length: `TWILIO_MAX_CALL_SECONDS` (600 by default)
- Phone input retained for at most 20 seconds; synthesis output for at most 10 seconds per packet
- Playback uses short marked segments with ~800 ms outstanding audio to bridge acknowledgments over network round trips

---

## Voice interruptions

Set `VOICE_INTERRUPTION_ENABLED=true` in `.env` to classify speech that overlaps Scout's playback.

Scout continues the same answer for clear listening acknowledgments, and gives the caller a turn for questions, corrections, or confusion. Short inputs like "no" and "what" are sent with conversation context to decide.

**Speculative pause option:**
Set `VOICE_INTERRUPTION_SPECULATIVE_PAUSE=true` to temporarily pause sustained caller speech after a grace period, retaining the queued audio. An acknowledgment then resumes without restarting the answer. Defaults to `false`.

**Configuration knobs:**

| Variable | Default | Description |
|---|---|---|
| `VOICE_INTERRUPTION_ENABLED` | `false` | Enable/disable the feature |
| `VOICE_INTERRUPTION_SPECULATIVE_PAUSE` | `false` | Pause on sustained speech |
| `VOICE_INTERRUPTION_GRACE_MS` | `350` | Grace period before speculative pause |
| `VOICE_INTERRUPTION_TIMEOUT_MS` | `4000` | Max time to wait for classification |
| `VOICE_INTERRUPTION_TRANSCRIPT_TIMEOUT_MS` | `1500` | Recovery timeout when speech ends without a transcript |

> Deploy the frontend and backend together — voice calls require protocol version 2.

---

## Retrieval providers

Campus Voice supports three retrieval providers, selectable from the compact dropdown in the UI:

| Provider | Description |
|---|---|
| **Decisions** (default) | `openai/gpt-6-luna-decisions` via OpenRouter navigates PageIndex documents and selects source text |
| **Jev** | Alternative retrieval via Typesafe API |
| **Normal LLM** | GPT-6 Luna chooses between a streaming reply and a `read_pageindex` source batch |

The selection applies to text chat and new voice calls, stays fixed during a reply or call, and starts at **Normal LLM** on each page load. Switching providers preserves the current conversation.

**Normal LLM details:**
- Uses `openai/gpt-6-luna` through OpenRouter
- Greetings/clarifications: one model call
- Factual questions: two calls (select sources → answer with evidence)
- Up to six source nodes across three branches per batch, three documents per batch
- Streams decoded reply text into chat and the voice sentence queue in real time

**Configuration:**

| Variable | Default | Description |
|---|---|---|
| `RETRIEVAL_MODE` | `decisions` | Standalone agent default provider |
| `RETRIEVAL_MAX_ROUNDS` | `12` | Max retrieval rounds per turn |
| `RETRIEVAL_MAX_SECONDS` | `20` | Max seconds for retrieval |
| `RETRIEVAL_REQUEST_TIMEOUT` | `5` | Per-request timeout (seconds) |
| `NORMAL_LLM_REQUEST_TIMEOUT` | `15` | Per model call timeout (seconds) |
| `NORMAL_LLM_MAX_SECONDS` | `45` | Max seconds per turn |
| `NORMAL_LLM_EVIDENCE_BYTES` | `32000` | Max source evidence bytes |

---

## LangSmith

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env` to enable tracing. `LANGSMITH_PROJECT` is optional (defaults to `tiet-chatbot`).

Traces follow decisions, retrieved sources, and answer generation — recording evidence, timing, usage, and errors while excluding credentials and client objects. Traces are grouped by `thread_id` and flushed at shutdown.

---

## Verification

Run the Python unit suite:

```bash
uv run python -m unittest \
  Agent.test_documents \
  Agent.test_decisions \
  Agent.test_retrieval \
  Agent.test_graph \
  Agent.test_tracing \
  backend.test_voice_language \
  backend.test_voice_activity \
  backend.test_voice_pipeline \
  backend.test_voice_interruption \
  backend.test_voice_response \
  backend.test_agent_endpoints \
  -v
```

Run deterministic browser playback lifecycle tests:

```bash
node --test frontend/src/lib/voicePlayback.test.mjs
```

> Tests mock model providers and API calls. Use configured API keys to separately evaluate live answer quality, latency, and cost on representative questions.
