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
Traces show `jev_retrieval`, each combined `jev_decision`, `fetch_local_source`, and the final answer-model call.
Jev request inputs, returned decisions, probabilities, available confidence, reported token usage, and timing are recorded.
This exposes observable decisions and evidence, not an internal reasoning transcript.

## Verification

After installing dependencies, run:

```bash
uv run python -m unittest Agent.test_documents Agent.test_retrieval Agent.test_graph backend.test_voice_pipeline backend.test_agent_endpoints -v
```

The suite uses fake model responses and a mocked TypeSafe HTTP transport to verify call structure, retrieval limits, source validation, chat streaming, follow-up isolation, and voice cancellation.
Live answer accuracy and latency require configured API keys and a separate comparison using representative questions.
For that comparison, include multi-document questions, fee and eligibility exceptions, Hindi/Hinglish, follow-ups, and questions absent from the corpus.
Check the actual retrieved evidence and final answers, especially premature readiness, and measure complete response time and cost in both retrieval modes.

