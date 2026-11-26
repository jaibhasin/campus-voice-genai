# Campus Voice

Campus Voice is an AI-powered campus assistant for Thapar Institute of Engineering & Technology (TIET) that answers student queries about admissions, fees, hostel allocation, programmes, and more. It supports both text chat and voice conversations, using retrieval-augmented generation over official TIET documents to give accurate, source-grounded answers.

---

## How to Run

There are two ways to run Campus Voice:

| Mode | What you get |
|---|---|
| **Option A — Local only** | Text chat + browser voice (microphone). No phone needed. |
| **Option B — With Twilio** | Everything in Option A, plus real phone calls to/from Scout. |

---

## Option A — Run Locally (Recommended to get started)

### 1. Set up environment variables

Copy `.env.example` to `.env` and fill in:

```
OPENROUTER_API_KEY=   # required — for retrieval and answers
SARVAM_API_KEY=       # optional — enables browser voice (mic/speaker)
```

### 2. Start the backend

```bash
uv venv
uv pip install -r requirements.txt
uv run uvicorn backend.main:app --reload --port 8000
```

Backend runs at `http://localhost:8000`.

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:3000`. Open it in your browser — you're good to go.

---

## Option B — Run with Twilio Phone Calls

This adds real inbound/outbound phone calls on top of Option A. You need a Twilio account with Media Streams access (not available on current trial — upgrade or use an older account).

### 1. Add Twilio keys to `.env`

```
TWILIO_ENABLED=true
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=       # E.164 format, e.g. +1...
TWILIO_ALLOWED_PHONE_NUMBER=  # your mobile in E.164, e.g. +91...
TWILIO_PUBLIC_BASE_URL=    # fill this in after step 3
```

> For calls to India, use a non-Indian Twilio number and enable India in Twilio Voice geographic permissions.

### 2. Start the backend (single worker, no reload)

```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### 3. Start ngrok to expose the backend

```bash
ngrok http 8000 --traffic-policy-file ngrok-telephony.yml --inspect=false
```

Copy the HTTPS URL ngrok prints (e.g. `https://abc123.ngrok-free.app`) and set it as `TWILIO_PUBLIC_BASE_URL` in `.env`, then restart the backend.

### 4. Configure your Twilio number

In the Twilio Console, set your number's incoming voice webhook to:

```
https://<your-ngrok-domain>/api/telephony/voice   (POST)
```

### 5. Make a call

**Inbound:** Dial your Twilio number from your permitted mobile.

**Outbound (Scout calls you):**

```bash
uv run python -m backend.call_scout --request-id call-001
```

Use a unique `--request-id` each time. Repeating the same ID returns the original result without redialling.

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | Retrieval and answers via OpenRouter |
| `SARVAM_API_KEY` | No | Browser + phone voice (STT/TTS) |
| `TYPESAFE_API_KEY` | No | Jev retrieval provider and voice interruption |
| `TWILIO_ENABLED` | No | Set `true` to enable phone calls |
| `TWILIO_ACCOUNT_SID` | Twilio only | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio only | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Twilio only | Your Twilio number (E.164) |
| `TWILIO_ALLOWED_PHONE_NUMBER` | Twilio only | Your permitted mobile (E.164) |
| `TWILIO_PUBLIC_BASE_URL` | Twilio only | ngrok HTTPS origin, no trailing slash |
| `LANGSMITH_API_KEY` | No | Enables LangSmith tracing |

See `.env.example` for all options with defaults.

---

## Retrieval Providers

Use the dropdown in the UI to switch between providers:

| Provider | Description |
|---|---|
| **Normal LLM** (default on load) | GPT-6 Luna selects sources then answers |
| **Decisions** | OpenAI Decisions navigates PageIndex documents |
| **Jev** | Alternative retrieval via Typesafe API |

---

## Running Tests

```bash
uv run python -m unittest \
  Agent.test_documents Agent.test_decisions Agent.test_retrieval \
  Agent.test_graph Agent.test_tracing backend.test_voice_language \
  backend.test_voice_activity backend.test_voice_pipeline \
  backend.test_voice_interruption backend.test_voice_response \
  backend.test_agent_endpoints -v
```

```bash
node --test frontend/src/lib/voicePlayback.test.mjs
```
