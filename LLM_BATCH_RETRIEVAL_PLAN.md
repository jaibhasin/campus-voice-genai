# GPT-6 Luna PageIndex agent

Status: implemented with focused local verification.

The `Normal LLM (GPT-6 Luna)` dropdown option uses one GPT-6 Luna agent for both conversation and PageIndex source selection.
For a greeting or clarification, Luna can respond directly.
For a factual college question, Luna selects multiple source nodes across up to three branches in one tool call, receives their actual text, and answers using the same model.
One model can require multiple API calls because source text becomes available only after a tool executes.

## Request flow

1. Read the current question, bounded conversation context, and cached document catalog.
2. Luna chooses `reply` for speech or `read_pageindex` with one shared list of at most six `source_ids`, constrained to actual unread source text.
3. Validate the entire selection, then fetch source text locally without intermediate navigation calls.
4. Luna reads the returned evidence and writes the reply, or requests one more batch for missing evidence.
5. After two batches, the final Luna call is forced to `reply` and must explain any unresolved evidence gaps.

The typical factual flow uses two calls to Luna.
The optional follow-up makes it three calls to the same model.
There is no separate planner or GPT-4.1-mini answer call in this mode.
The existing Decisions and Jev options retain their original behavior.

## Catalog and branch traversal

`Agent/batch_pageindex.py` builds a compact hierarchical catalog directly from the shared `DocumentStore`.
The current corpus has 23 document roots and 446 source chunks.
Catalog entries expose IDs at every depth, so the model can select a descendant source directly rather than opening each ancestor in a separate request.
Section summaries and original-page hints assist navigation but are never treated as factual evidence.
Original pages remain available for tables, footnotes, and gaps in section text.

The backend derives each source's actual document root from the loaded tree.
Luna does not have to repeat branch IDs or guess which outline contains a source.
The per-request strict schema includes only actual unread source IDs and caps the shared list at six.
Unknown IDs, outline IDs passed as sources, rereads, and oversized selections fail validation before any source is read.
Duplicate IDs within a batch are read once.
Sources from more than three documents are reported as omitted without rejecting the valid sources from the first three documents.
The selection can span multiple sections of one document or branches in different documents.
Per-turn evidence, seen-source IDs, history, and tool messages remain local to each request.

Evidence allocation visits the first requested source in each branch before taking a second source from one branch.
Retain whole source chunks and preserve returned provenance.
Report selected chunks that do not fit as omitted, rather than silently clipping their text or claiming they were checked.
The next batch cannot reread sources already fetched in the current turn.

## Model and speech behavior

`Agent/normal_llm.py` uses `openai/gpt-6-luna` through the existing OpenRouter credentials.
Reasoning effort is `none`, consistent with normal Luna function calling in [OpenAI's model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna).
The live gateway capability probe returned a valid tool call for this exact model.

The same pooled model client handles source selection and final text.
There are no hidden retries or calls to the existing answer model in this mode.
Greetings, short utterances, clarifications, and factual routing are contextual model decisions rather than local keyword filters.
Accepted voice language and concise spoken style apply to every call.

Every response chooses exactly one strict tool: `read_pageindex` or `reply`.
The request requires a tool choice and disables parallel tool calls.
The reply tool explicitly commits the model to user-facing text, allowing decoded `reply.text` to stream immediately without waiting for response completion.
Discard ordinary content accompanying a tool call and never send source arguments or the reply JSON envelope to chat or TTS.
Incomplete JSON escapes and split Unicode surrogate pairs wait until they can be decoded safely.
The final call permits only `reply`, and the existing voice sender converts complete sentences while later words are still being generated.

## Graph and dropdown integration

`Agent/graph.py` routes the selected `llm_batch` provider to a dedicated graph node while preserving existing thread history.
This node emits the same token, source-progress, and completion events used by chat and voice.
It skips the separate conversation summarizer and uses bounded recent context plus any existing summary.
Switching providers keeps the conversation but resets retrieved evidence on the next question.

`backend/main.py` accepts `llm_batch` for chat, uploaded voice chat, and the voice WebSocket.
`frontend/src/components/ProviderSelect.jsx` exposes the new option below Call Scout.
Selection stays disabled during an active response or call and applies to the next call.
Decisions remains the page's default while latency and source coverage are evaluated.
The optional Jev interruption classifier continues to manage overlapping speech under its existing configuration.

## Limits and lifecycle

The initial limits are three documents and six distinct sources per batch, two batches, a 96,000-byte catalog, a 160,000-byte total model request, and 32,000 bytes of source evidence.
Each model request has a 15-second deadline within a 45-second total turn budget.
`NORMAL_LLM_REQUEST_TIMEOUT`, `NORMAL_LLM_MAX_SECONDS`, and `NORMAL_LLM_EVIDENCE_BYTES` configure the timing and evidence limits.
Use `RETRIEVAL_MODE=llm_batch` for the standalone agent default.

An oversized catalog or request fails explicitly instead of silently truncating the corpus.
Invalid tool selections return a bounded error to Luna and consume a batch attempt.
A deadline aborts pending model work, and cancellation propagates to the voice response owner.
The model pools close with the existing application shutdown lifecycle.
The recent cold-tokenizer fix remains in place.

## Tracing and verification

LangSmith records `normal_llm_agent`, each `luna_agent` call, and `read_pageindex` spans beneath the existing chat or voice trace.
Source provenance, selected branches, omitted chunks, request size, model usage, timing, and errors are observable without including client credentials.

Focused local tests cover deep-node selection, derived document branches, the shared six-source schema, unread-ID choices, schema isolation, whole-batch validation, document and evidence limits, omitted-source follow-ups, one-call greetings, same-model factual responses, bounded follow-up reads, per-turn isolation, concurrent turns, deadlines, and cancellation.
Streaming regressions verify early text delivery, split Unicode and JSON escapes, suppressed tool preambles, and first-sentence TTS conversion before model completion.
Native SDK HTTP fixtures verified synchronous and asynchronous tool-call parsing, tool result linkage, usage reporting, and parented traces.
Graph and endpoint checks verified provider selection, preserved context, voice language, and that the old answer model is not called for `llm_batch`.

The live gateway accepted strict reply and source-selection schemas against synthetic documents, using one call for a greeting and two calls for a six-source answer.
Real-corpus checks on 2026-10-14 passed for a greeting, scholarships, and bachelor's/master's programmes, using one, two, and two calls respectively with no rejected selections.
First reply text arrived at approximately 1.86, 3.38, and 3.17 seconds respectively, and each streamed reply matched the completed answer.
The 160 agent/backend tests and Ruff checks passed after the real-corpus follow-up fixes.
Microphone input, real TTS audio, browser playback, and comparative audible latency measurements remain unverified.
Evaluate warm and cold calls using the same corpus, question, conversation, and speech settings before claiming faster responses or promoting the default.
