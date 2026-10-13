# GPT-6 Luna batch retrieval plan

Status: proposed, implementation not started.

Add `Normal LLM (GPT-6 Luna)` to the existing retrieval dropdown for chat and voice.
One Luna request should inspect a compact catalog spanning multiple levels of the document tree and select source nodes from up to three relevant paths together.
The server then fetches those sources locally and passes actual source text to the existing answer model.
Fewer retrieval round trips are the intended improvement; latency and answer quality must be measured before claiming a speedup.

## Current behavior and motivation

The dropdown offers `Decisions` and `Jev`.
Both use a retrieval controller that selects one navigation action or source per request.
The original `RETRIEVAL_MODE=llm` instead uses a tool-selection loop and is not the proposed batch retriever.

The current corpus contains 23 document roots, 555 total targets, and 446 source chunks.
A simple grouped catalog containing source references, titles, short summaries, and chunk counts is approximately 71 KB before further hierarchy compression.
Catalog construction is local work and does not require another model call.

Today's completed Decision API hostel and scholarship turns spent 5.85 and 6.58 seconds in retrieval across four and six sequential decisions.
Answer generation added 5.48 and 5.23 seconds respectively.
The scholarship turn selected a large subsection and stopped at the evidence limit before reading its third chunk.
These observations motivate fewer navigation calls and deliberate evidence allocation across requested topics.
They are individual observations, not a comparative benchmark.

## Dropdown and request routing

Keep the existing provider options and add the new option with request value `llm_batch`.
Use the label `Normal LLM (GPT-6 Luna)` and retain `Retrieval provider` as the accessible label.
The selected value applies to both chat requests and the next voice call.
Keep selection disabled while a chat response streams or a call is open, matching the current interaction.
Retain the current default during evaluation so users explicitly choose the new option.

Extend chat and voice endpoint validation to accept `llm_batch`.
Replace the graph's two-provider initialization assumption with an explicit registry containing `decisions`, `jev`, and `llm_batch`.
Each provider receives the shared immutable document store and maintains request-local retrieval state.
Support `RETRIEVAL_MODE=llm_batch` for standalone agents without repurposing the existing `llm` mode.
Selecting this option changes retrieval only; GPT-4.1-mini remains the answer model for the initial comparison.
Jev continues to classify overlapping voice utterances under the existing interruption setting.

## Model and transport

Use the normal GPT-6 Luna model, not the Decisions variant.
The official model supports structured outputs and reasoning effort `none`.
See the [GPT-6 Luna model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna).

Prefer the existing OpenRouter connection and credentials, with `openai/gpt-6-luna` as the proposed gateway model ID.
Before implementation is considered complete, verify the gateway model ID, structured-output support, reasoning parameter, and usage reporting with a live request.
OpenAI documentation establishes the underlying model capabilities; it does not establish the gateway's availability or parameter mapping.
Configure reasoning effort `none` initially and request a compact structured selection rather than explanatory prose.
Use an asynchronous pooled client with an explicit total deadline and no hidden retries.
Close the client during the existing application shutdown lifecycle.

## One request selects several paths

Build a stable catalog when the document store loads.
Present document and section ancestry together with directly selectable source IDs, short summaries, page references, and chunk relationships.
Represent artificial grouping outlines as catalog structure rather than requiring the model to select them one at a time.
Keep original-page references available for tables, footnotes, and gaps in section text.
Deduplicate repeated titles and preserve every source's document and section ancestry.

The request contains the current question, bounded recent conversation and running memory, the catalog, and any evidence from a previous batch.
Use the existing follow-up context handling so questions such as "Does that include electricity?" resolve against the conversation.
Treat catalog summaries and conversation as navigation data, not verified college facts.

The structured result contains:

- `action`: `fetch_sources`, `answer_without_sources`, or `insufficient_sources`.
- `paths`: zero to three entries, each containing a catalog-defined branch ID and an ordered list of catalog-defined source IDs.
- `coverage`: the requested topic or question part each path is intended to address.

Allow one path when sufficient and two or three when the question needs alternatives, exceptions, or multiple topics.
Allow multiple source nodes within each path, with at most six distinct source nodes per request.
Source IDs may be at different tree depths or in different documents.
`answer_without_sources` is appropriate for greetings, clarifications, and off-topic responses, never unsupported factual answers.
Do not use local keyword or utterance-length shortcuts for this routing.

Validate the action, path count, source count, ID membership, source kind, ancestry, and duplicates before fetching anything.
Validate the whole batch before applying it, and reject malformed or unknown references without substituting a different source.
Schema validity does not establish that selected sources are relevant or sufficient.

For example, "What are hostel costs and available scholarships?" may select the hostel fee source and hostel conditions under one branch, plus scholarship eligibility and relevant exceptions under another branch.
Both branches are selected in the same Luna response.
The model compares their navigation metadata during selection; it checks their factual text only after the server fetches it.

## Source execution and answer handoff

Fetch the validated batch locally without another navigation decision between nodes.
These sources already live in memory, so additional HTTP requests or worker threads are unnecessary.
Preserve deterministic ordering, cancellation checks between fetches, and the existing per-source progress events.
Deduplicate overlap between section text and original pages when it adds no new evidence.

Allocate evidence across the selected paths before reading, rather than letting the first large subsection consume the entire budget.
Prefer complete source chunks, table headings, policy conditions, and adjacent exceptions.
For split sections, track selected and omitted parts explicitly and retain their order.
If all selected material cannot fit, omit whole lower-priority chunks and record which coverage remains incomplete.
Do not silently halve source text or describe an unread section as checked.

Return the common `RetrievalResult` shape so the graph can reuse its answer handoff.
Add batch selection and fetched source entries to its history, with explicit limitations for omitted or unavailable material.
Compute the available evidence allowance using the actual answer prompt, current question, retained history, and response reserve.
The effective allowance is the smaller of the batch evidence cap and the answer context space available.
Keep tokenizer initialization off the response path and preserve the recent cold-start fix.

## One optional follow-up retrieval

The normal factual flow is one Luna selection followed by one existing answer-model call.
Do not insert an unconditional second Luna call just to declare readiness.
The answer model evaluates the fetched text while composing the answer.

For this provider, give the answer node one typed `request_more_sources` tool containing the missing question parts.
When evidence is insufficient, it must request this tool before streaming user-facing answer text.
That tool triggers one additional Luna batch using the existing evidence, the catalog, and the named gaps.
The follow-up excludes already-read sources and fetches newly selected nodes under the remaining evidence and time budgets.
Invoke the answer model again with tool use disabled for the final response.
If coverage is still incomplete, answer only supported parts and state the limitation naturally.

Buffer model output until a tool call or user-facing text is identified, so tool arguments never enter chat or TTS.
Once user-facing answer text begins, do not initiate another retrieval batch for that turn.
The correction flow therefore costs up to four model requests: selection, answer requesting more evidence, follow-up selection, and final answer.
Trace those costs honestly; one-call traversal does not mean one total model request or complete source inspection within that selection call.

## Initial limits and failure behavior

Use separate batch-provider limits so the existing typed-decision limits remain meaningful.
Initial proposed limits are a 96 KB catalog, 160 KB total selection request, 32 KB evidence ceiling, three paths, six sources per batch, two retrieval batches, and a 10-second total retrieval budget.
Each Luna request has a five-second deadline bounded by the remaining retrieval budget.
These are starting parameters to tune using latency and coverage measurements.
The answer context allowance still takes precedence over the evidence ceiling.

If a future corpus exceeds the catalog allowance, locally rank candidates across the entire corpus using titles, summaries, and conversation context before rendering a bounded catalog.
Mark the catalog as incomplete and expose the omitted candidate count.
Never take the first N documents by file order or treat a filtered catalog as proof that information is unavailable.
Benchmark recall on the enlarged-corpus fixture before relying on this overflow behavior.

Timeout, refusal, missing credentials, invalid output, oversized requests, and exhausted budgets produce explicit retrieval limitations.
Do not silently switch to Jev or Decision API, which would obscure the comparison and add delays.
Cancellation immediately aborts outstanding planner or answer work and preserves the existing response ID rules for TTS and playback.

## LangSmith evidence

Retain the existing root chat or voice trace and label the selected provider `llm_batch`.
Add spans for catalog preparation, `llm_batch_select`, local source fetches, optional gap retrieval, and `llm_answer`.
Record model and gateway, batch index, selected paths and IDs, candidate counts, catalog completeness, input size, usage, elapsed time, evidence size, omitted sources, stop reason, and cancellation.
Exclude credentials and client objects.

For voice evaluation, record elapsed durations from accepted transcript to first answer token, first complete sentence submitted to TTS, first audio packet sent, and browser playback start.
Use elapsed time within each clock domain; correlate call and response IDs rather than subtracting unsynchronized server and browser timestamps.
Distinguish generation cancellation, speech-provider failure, and caller interruption.
Keep test traces out of the production project during verification.

## Implementation sequence

| Step | Files and responsibility | Reviewable outcome |
| --- | --- | --- |
| 1 | `Agent/documents.py` and document tests | Cached catalog with direct references across hierarchy levels and chunk relationships. |
| 2 | New `Agent/llm_batch.py` and batch retrieval tests | Async Luna selection, schema validation, source batching, budgets, common result contract, and tracing. |
| 3 | `Agent/graph.py` and graph tests | Three-provider registry and optional bounded gap retrieval before answer streaming. |
| 4 | `backend/main.py`, endpoint tests, and voice pipeline tests | Chat and voice accept the provider and preserve call cancellation and lifecycle behavior. |
| 5 | `frontend/src/components/ProviderSelect.jsx` and frontend verification | Third dropdown option reaches both request paths and remains disabled during active responses and calls. |
| 6 | `.env.example` and `README.md` | Model settings, limits, selection behavior, and evaluation instructions. |

During implementation, make small atomic commits after each coherent change.
Preserve unrelated working-tree changes and regenerate dependency lockfiles using their package tooling only if dependencies change.

## Verification and adoption criteria

Deterministic tests must prove that one planner request can select nodes several levels below document roots and retrieve sources from two or three branches without intervening navigation calls.
Cover one-path selection, split sections, cross-document overlap, greetings, contextual follow-ups, Hindi and Hinglish, missing evidence, conflicts, invalid IDs, wrong ancestry, duplicate selections, oversized catalogs, budget allocation, timeout, refusal, and cancellation.
Prove that the optional gap path runs at most once, excludes already-read sources, and never sends tool arguments to chat or TTS.
Keep Jev and Decision API regression tests passing, including concurrent requests selecting different providers.

Verify the dropdown in chat and real voice calls, including changing providers between calls and cancelling while Luna is selecting sources.
Run the existing Python suites, playback tests, lint, and frontend build appropriate to the implementation.

Benchmark all three providers on the same question set, with the same answer model, document corpus, conversation state, and speech configuration.
Include hostel details, hostel fees and exceptions, scholarship overview and eligibility, hostel plus scholarship questions, contextual follow-ups, multilingual questions, greetings, and unanswerable requests.
Run at least five repetitions per factual question and separate cold-start from warm measurements.
Compare median and tail retrieval latency, time to first spoken answer, total model requests, tokens, cost, evidence coverage, incorrect claims, cancellations, and failures.

The initial target is at least a 30 percent reduction in median retrieval latency on the representative factual set without worse source coverage or unsupported answers.
Also require improvement in time to first spoken answer and no material tail-latency regression.
This target is an acceptance criterion, not a predicted result.
If the larger catalog erases the savings, tune catalog compression and selection limits before promoting the option.
Keep the option selectable for evaluation until these results support changing the default.
