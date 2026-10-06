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

## Environment variables

Copy `.env.example` to `.env` in the project root and fill in your keys.
The backend uses `TYPESAFE_API_KEY` for Jev retrieval, `OPENROUTER_API_KEY` for final answers, and `SARVAM_API_KEY` for voice features.

## Jev retrieval

Jev receives the question, recent conversation, fetched source text, and available retrieval targets.
Each API request asks both `action` and `next_read` together.
These questions are evaluated independently, so candidate descriptions are supplied once in the shared `unread_sources` state and the selection options refer to those IDs.
The shared state also reports the unread candidate count and whether more candidates are outside the visible menu, so the stop decision can account for further retrieval options.
The only action options are `read_more` and `ready_to_answer`.
When Jev chooses `read_more`, code executes the selected local target and sends the updated evidence in the next request.
Opening a document exposes its sections and pages; reading a section or page adds actual text to the evidence packet.
On `ready_to_answer`, the LLM receives the evidence and source references and streams one final answer.
The LLM has no retrieval tools in Jev mode.
The same flow serves text chat and voice.

Source summaries help navigation and are not treated as factual evidence.
Large sources are split into accessible parts without dropping text, and large candidate menus can be browsed through `more_candidates`.
Round, context, source-exhaustion, and error stops are passed to the answer writer as limitations, never as a Jev readiness decision.
Recent conversation sent to Jev is bounded to six messages and 4,000 UTF-8 bytes; the current question is not silently truncated.
An oversized question produces an explicit retrieval limitation.
Evidence is collected fresh for each question, while user and assistant conversation stays scoped to `thread_id`.

`JEV_MAX_ROUNDS` defaults to 12 and includes document-opening and candidate-navigation requests.
`JEV_MAX_SECONDS` defaults to a 20-second elapsed retrieval budget, checked between requests.
`JEV_REQUEST_TIMEOUT` defaults to 5 seconds for HTTP operations, with an additional total deadline for each asynchronous voice request.
Automatic SDK retries are disabled and HTTP/2 clients reuse connections.
The request budget is conservatively bounded to 28,000 UTF-8 bytes and source evidence to 18,000 bytes.
These limits bound retrieval; they do not guarantee answer completeness or model accuracy.

Set `RETRIEVAL_MODE=llm` and restart the backend to compare against the original LLM tool-selection loop.
Jev errors never silently switch retrieval to the LLM.
Index generation and existing PageIndex exports are unchanged.

## LangSmith

Set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, and optionally `LANGSMITH_PROJECT` in `.env`.
Each request has one `Scout` or `Scout-Voice` root trace, grouped by its conversation `thread_id`.
Under it, `jev_retrieval` contains each combined `jev_decision` model span and each `fetch_local_source` tool span.
The final OpenRouter model span is named `llm_answer`; the optional LLM retrieval baseline uses `llm_agent` spans and native tool spans.
Jev request inputs, returned decisions, probabilities, available confidence, reported token usage, and timing are recorded.
Model spans identify the provider and model, normalize reported token usage, and capture errors and cancellation.
OpenRouter streaming explicitly requests usage, and local read spans include document and section/page metadata plus fetched content.
API credentials and client objects are excluded from custom trace inputs.
Uploads remain buffered during responses and are flushed during server shutdown.
This exposes observable decisions and evidence, not an internal reasoning transcript.

## Verification

After installing dependencies, run:

```bash
uv run python -m unittest Agent.test_documents Agent.test_retrieval Agent.test_graph Agent.test_tracing backend.test_voice_pipeline backend.test_agent_endpoints -v
```

The suite uses fake model responses and mocked TypeSafe/OpenRouter HTTP transports to verify call structure, retrieval limits, source validation, chat streaming, follow-up isolation, and voice cancellation.
Trace tests exercise the real SDKs and exported LangSmith spans to check parent relationships, call counts, inputs/outputs, usage, failures, cancellation, and credential exclusion in both retrieval modes.
Live answer accuracy and latency require configured API keys and a separate comparison using representative questions.
For that comparison, include multi-document questions, fee and eligibility exceptions, Hindi/Hinglish, follow-ups, and questions absent from the corpus.
Check the actual retrieved evidence and final answers, especially premature readiness, and measure complete response time and cost in both retrieval modes.
