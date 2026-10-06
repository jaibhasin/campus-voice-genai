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

Voice calls use the same accepted conversation language for answer generation and speech synthesis.
Low-confidence detections and short follow-ups preserve an established language; explicit language requests switch immediately.
Check-ins wait for 60 seconds of inactivity after speech, answers, and browser playback finish, and use the accepted language for English, Hindi, and Punjabi calls.

## Environment variables

Copy `.env.example` to `.env` in the project root and fill in your keys.
The backend uses `TYPESAFE_API_KEY` for Jev retrieval, `OPENROUTER_API_KEY` for final answers, and `SARVAM_API_KEY` for voice features.

## Jev retrieval

- **Flow:** Jev selects local PageIndex sources, then the LLM streams one answer using the fetched text and references.
- **Decisions:** Each request asks `action` (`read_more` or `ready_to_answer`) and `next_read` together, using shared candidate descriptions and evidence.
- **Sources:** Jev chooses a document, then a section, then the actual text to read.
  Each choice opens only that section's children, preserving the document's hierarchy.
  Large sections are grouped into smaller lists, and original pages have their own entry.
  Full source text is preserved across parts; splitting prefers complete lines so table headings and conditions stay together where possible.
- **Choice lists:** Document lists show up to 24 entries, and section lists show up to 12, within a 6,000-byte menu budget.
  Jev can request more choices, return to a parent section, switch documents, or explicitly resume the document it just left.
  Titles and short summaries guide these choices; only fetched text supports factual answers.
- **Conversation:** Chat and voice share this flow, with fresh evidence per question and history scoped to `thread_id`.
  Jev receives up to six recent messages (4,000 UTF-8 bytes).
  Its request includes the last eight retrieval decisions, while the complete decision history remains available in traces and the answer handoff.
- **Limits:** Defaults are 12 rounds, a 20-second budget checked between requests, and a 5-second HTTP timeout (also a total deadline per async request).
  Request and evidence budgets are 28,000 and 18,000 UTF-8 bytes; SDK retries are disabled.
  Every request is measured before sending, and each new choice list is fitted around the text already read.
  Reading another source no longer requires keeping the previous choice list alongside it.
- **Incomplete retrieval:** Errors or exhausted limits are passed to the answer writer as limitations.
  The LLM has no retrieval tools in Jev mode, and Jev errors do not trigger an automatic LLM fallback.
- **Compare modes:** Set `RETRIEVAL_MODE=llm` and restart the backend to use the original LLM tool-selection loop.

## LangSmith

- **Setup:** Set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, and optionally `LANGSMITH_PROJECT` in `.env`.
- **Trace flow:** `Scout` / `Scout-Voice` → `jev_retrieval` → `jev_decision` and `fetch_local_source`, followed by `llm_answer`.
  Traces are grouped by `thread_id`; LLM retrieval mode uses `llm_agent` and native tool spans.
- **Recorded:** Inputs, decisions, fetched text, source metadata, probabilities/confidence, reported token usage, timing, and errors.
- **Excluded:** API credentials and client objects are excluded from custom trace inputs.
- **Uploads:** Buffered during responses and flushed at shutdown.
  Traces show observable decisions and evidence, not internal reasoning.

## Verification

After installing dependencies, run:

```bash
uv run python -m unittest Agent.test_documents Agent.test_retrieval Agent.test_graph Agent.test_tracing backend.test_voice_language backend.test_voice_activity backend.test_voice_pipeline backend.test_agent_endpoints -v
```

The suite uses fake model responses and mocked TypeSafe/OpenRouter HTTP transports to verify call structure, retrieval limits, source validation, chat streaming, follow-up isolation, voice language stability, inactivity check-ins, and voice cancellation.
Retrieval regressions cover nested sections, wide lists, document switching and resuming, and reading a source that would have exceeded the budget with the old choice list.
Trace tests exercise the real SDKs and exported LangSmith spans to check parent relationships, call counts, inputs/outputs, usage, failures, cancellation, and credential exclusion in both retrieval modes.
Live answer accuracy and latency require configured API keys and a separate comparison using representative questions.
For that comparison, include multi-document questions, fee and eligibility exceptions, Hindi/Hinglish, follow-ups, and questions absent from the corpus.
Check the actual retrieved evidence and final answers, especially premature readiness, and measure complete response time and cost in both retrieval modes.
