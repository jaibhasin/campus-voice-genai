# Voice interruption classification plan

Status: implemented; controlled validation passed and enablement remains opt-in.
Branch: `voice-interruption-classifier`.

## What the caller should experience

Scout is explaining hostel fees when the caller says "okay".
Jev identifies a listening acknowledgment, and Scout continues the same explanation.
If playback was temporarily paused, it resumes at the same position.

The caller says "wait, does that include electricity?".
Jev identifies a request to take a turn, Scout stops the explanation, and the existing voice agent answers the question.

The caller says only "no" or "what?".
Both utterances go to Jev with conversation context.
Rejection, confusion, corrections, questions, and answers to Scout's questions count as taking a turn, even when they contain one word.
If the result is uncertain, Scout gives the caller the floor.

## Findings in the current code

| Location | Current behavior | Required change |
| --- | --- | --- |
| `frontend/src/components/CallOverlay.jsx`, speech-start handler | Every VAD speech-start event invokes `stopPlaybackForBargeIn()`. | Speech detection starts a reversible decision window. |
| `CallOverlay.jsx`, playback controller | Stopping invalidates decode work and stops all scheduled audio sources. | Add temporary pause/resume separately from permanent discard. |
| `backend/voice_pipeline.py`, final-transcript handler | Every nonempty final transcript updates language, cancels the agent, resets TTS text, and starts an answer. | Decide whether the caller is taking a turn before those actions. |
| `voice_pipeline.py`, TTS sender and receiver | `RESET` clears only the sender's current text buffer; the shared TTS socket can still deliver old audio. | Isolate canceled synthesis and identify every response. |
| `Agent/jev.py` | An asynchronous TypeSafe client already supports typed Choice questions, explicit timeouts, and no retries. | Reuse this transport for one separate interruption decision. |
| `backend/voice_activity.py` | Busy flags protect call inactivity check-ins. | Treat paused playback and pending decisions as busy activity. |

The response may finish generating while its audio is still playing.
Therefore, an unfinished agent task alone is not a reliable indication that Scout is speaking.
The browser's playback state must participate in overlap detection.

## Scope

Implement this behavior in voice calls using the existing Sarvam STT, TTS, and Jev services.
Keep Jev responsible for the turn decision and the existing voice agent responsible for answering.
Use one Jev request per completed overlapping utterance, including short inputs such as "no", "what", "yes", and "okay".
Normal input while Scout is listening follows the existing answering path without interruption classification.
User speech while the agent is thinking can supersede the pending answer through the existing turn path.

Support acknowledgments and interruptions in the languages the current speech pipeline supports, including native scripts and mixed-language utterances.
Language coverage is an acceptance requirement to evaluate, not a promise that every language will work equally well.

## Turn decision contract

Add `backend/voice_interruption.py` for the classifier contract, result validation, deadlines, and decision policy.
Use an injected Jev client so policy can be checked independently from a live network request.

The request contains bounded data:

- The completed caller utterance and detected language, when available.
- The current response ID and utterance ID.
- Whether speech began during playback or a temporary playback pause.
- The most recent user question and a short recent conversation excerpt.
- A bounded excerpt of the current assistant response and whether an answer is being requested.

The current code has no exact text-to-playback alignment.
Label the assistant excerpt as generated text rather than claiming that the caller heard every word.
When the caller might be answering a question, uncertainty favors taking a turn.

Ask one typed Choice question with three code-defined options:

| Choice | Meaning | Application behavior |
| --- | --- | --- |
| `acknowledgment` | The caller is clearly just following the explanation. | Continue or resume the existing response. |
| `take_turn` | The caller asks, corrects, rejects, expresses confusion, requests a stop, or answers a question. | End the old response and accept the caller's turn. |
| `uncertain` | The available context does not establish a listening acknowledgment. | Give the caller the floor. |

Require the complete utterance before deciding to ignore it.
"Okay, but what about scholarships?" must never be reduced to its opening "okay".
Do not use word count, duration, or a keyword list to permanently ignore an utterance.
Treat caller text and conversation excerpts as data rather than instructions to change the classification policy.

Validate the returned answer type and allowed choice using the existing TypeSafe response shape.
Record returned confidence and probabilities when present, but do not assume that they are calibrated.
Use an explicit `uncertain` option instead of inventing an untested confidence cutoff.
Missing credentials, timeout, invalid output, or request failure all resolve to taking a turn.

## Playback and decision sequence

1. On VAD speech start, create an utterance ID and capture whether the caller overlapped the current audible or paused response.
2. Keep playback running for a short configurable grace period so a brief acknowledgment can finish without immediately cutting Scout off.
3. If the caller continues speaking beyond that period, temporarily suspend the playback AudioContext while keeping microphone capture active.
4. On a nonempty final transcript, launch the Jev decision asynchronously and keep receiving STT events.
5. Apply the result only if its call, utterance, and response IDs are still current and the caller has not started another utterance.
6. For an acknowledgment, resume retained playback if it was paused and keep the current agent/TTS response alive.
7. For taking a turn or uncertainty, permanently discard the old playback, cancel its generation and synthesis, and submit the caller's utterance through the normal voice answering path.

Use a 350 ms playback grace period and a 4,000 ms total classifier deadline after the final transcript.
The initial 1,000 ms deadline was revised after controlled integration calls took approximately 700-2,950 ms.
These configurable budgets and the small timing sample are not service guarantees.
If classification remains pending beyond the grace period, pause playback until a decision or its deadline arrives.
This bounds how long Scout continues talking over a possible interruption, while preserving a way to resume.

The microphone and playback already use separate AudioContexts in `CallOverlay.jsx`.
Suspend only the playback context, retaining its scheduled sources and playback timeline.
While paused, newly arriving chunks may be decoded and retained, but must not restart playback or overwrite the call's listening/decision state.
Use bounded retained audio and stop further synthesis if the bound is reached.
Never silently drop retained middle segments and then claim to resume the same response.

An empty final transcript or speech event that produces no transcript must not cancel the answer.
Resume after the speech-end event and a bounded transcript watchdog when there is no meaningful input.
If a newer utterance begins before a result is applied, keep playback paused, invalidate the obsolete decision, and preserve the accumulated caller input for the next decision.
If the assistant has naturally finished playback, there is nothing to resume; classification still uses the overlap captured at speech start.

## State and lifecycle

Keep response generation, audible playback, user speech, and classification as separate state dimensions.
Use monotonic per-call `response_id` and `utterance_id` values instead of inferring identity from UI labels.

| Situation | Playback | Agent/TTS | Idle check-in |
| --- | --- | --- | --- |
| Scout speaking normally | Running | May still be producing audio | Blocked |
| Possible interruption within grace period | Running briefly | Retained | Blocked |
| Sustained speech or pending decision | Temporarily paused | Retained within limits | Blocked |
| Confirmed acknowledgment | Running or resumed | Same response | Blocked until fully finished |
| Confirmed caller turn | Old playback discarded | Old response canceled | Blocked while processing caller input |
| Call ended | Stopped | All call tasks and sockets closed | Disabled |

Add an interruption-pending flag to `VoiceActivity` and distinguish paused playback from playback completion.
Do not emit `playback_done` for a temporary pause.
Language observation occurs only after an utterance has been accepted as a substantive turn.
A listening acknowledgment should not change the answer language or create a replacement answer.

Use explicit WebSocket events for pending, pause, resume, acknowledgment, accepted turn, and response cancellation.
Include the relevant IDs on events and make pause/resume/discard idempotent.
The transcript can display an acknowledgment as a caller entry without creating an empty assistant placeholder or switching to "thinking".
An accepted caller turn uses the existing transcript and answering UI behavior.

## Prevent canceled speech from returning

Replace the shared unowned response queue with response-scoped generation and TTS ownership.
Give each text token, completion event, and audio packet a response ID.
Use a compact versioned binary header carrying the response ID before each existing WAV payload.
The browser removes that header before decoding and rejects packets from canceled responses.
Check response identity again after asynchronous decoding completes.

Response IDs alone are insufficient if old provider output is mislabeled with the new current ID.
Bind a TTS collector to the response that owns its provider session.
Use response-scoped TTS sessions as the initial isolation strategy, closing the canceled session before its output can enter a new response.
Keep one STT connection for the whole call.
Assess TTS connection setup time during implementation; an alternative provider abort/reset mechanism is acceptable only after proving that old output cannot cross response boundaries.

On a real interruption, invalidate the response, cancel its agent and TTS tasks, discard its queues, stop its scheduled browser sources, and reject late events.
Do this even if the agent has already completed and only buffered speech remains.
Reuse the current cancellation handling that consumes child task cancellation without stopping the STT listener.
On an acknowledgment, preserve all of that response's ownership and queued audio.

## Files and implementation order

1. Add the classifier policy and one-request Jev adapter in `backend/voice_interruption.py`.
2. Generalize tracing purpose in `Agent/jev.py` only as needed so voice decisions are not labeled as retrieval.
3. Add response ownership and TTS isolation in `backend/voice_pipeline.py` before introducing reversible interruption behavior.
4. Add the matching response-aware audio protocol and separate pause/resume/discard controls in `frontend/src/components/CallOverlay.jsx`.
5. Connect the STT overlap snapshot, decision task, accepted-turn gate, and acknowledgment events.
6. Update `backend/voice_activity.py` so decisions and paused speech prevent inactivity check-ins.

Make small atomic commits for each complete logical change.
Keep a temporary feature flag off until the behavior has been validated.

## Example acceptance matrix

These are contextual examples, not a dictionary that replaces Jev.
Every completed overlapping utterance in this matrix is sent to Jev.

| Scout's situation | Caller input | Expected result |
| --- | --- | --- |
| Explaining hostel fees | "okay", "alright", "I'm listening" | Acknowledgment; same explanation continues. |
| Explaining hostel fees | "हाँ, सुन रहा हूँ" | Acknowledgment if context clearly indicates listening. |
| Explaining hostel fees | "ਹਾਂ, ਸੁਣ ਰਿਹਾ ਹਾਂ" | Acknowledgment if context clearly indicates listening. |
| Explaining hostel fees | "no" | Take a turn; allow rejection or correction. |
| Explaining hostel fees | "what?" | Take a turn; allow clarification. |
| Explaining hostel fees | "stop", "wait", "रुको", "ਰੁਕੋ" | Take a turn; stop old speech. |
| Explaining hostel fees | "okay, but does that include electricity?" | Take a turn; preserve the entire question. |
| Explaining hostel fees | "haan, but scholarship ka kya?" | Take a turn; recognize the mixed-language question. |
| Asking whether to compare CSE and ECE | "yes", "okay", "हाँ", "ਹਾਂ" | Take a turn; accept the answer to Scout's question. |
| Asking whether to compare CSE and ECE | "no" | Take a turn; accept the refusal. |
| Silent and listening | Any of the above | Normal caller turn; no overlap-only filter. |
| Speaking when Jev times out or returns invalid output | Any nonempty input | Take a turn through the bounded fallback. |

An acknowledgment is not a new question for the answer agent.
A one-word interruption does not require inventing a detailed question.
Use the existing conversation context for a short clarification or correction response, and allow the caller to continue.
Merge adjacent transcript fragments belonging to the same pending utterance before submitting them as a new answer request.

## Validation during implementation

### Classifier and backend checks

Add focused policy tests in `backend/test_voice_interruption.py` and extend `backend/test_voice_pipeline.py`.
Use mocked Jev results for deterministic state and cancellation checks, then evaluate the same examples against live Jev separately.
Mocked classifier output establishes application behavior, not live classification accuracy.

Check the following:

- Every nonempty overlapping final transcript, including "no" and "what", creates exactly one Jev decision.
- Nonoverlapping input reaches the existing agent normally.
- Acknowledgments keep the original response alive, do not change language, and create no new answer placeholder.
- Taking a turn cancels unfinished generation and already-finished generation's remaining playback alike.
- Old queued text, TTS audio, completion events, and asynchronous decode results cannot affect a successor response.
- A delayed Jev result cannot resume speech over a newer caller utterance.
- No-transcript speech events and empty transcripts resume the retained answer through the watchdog.
- Timeouts, missing credentials, malformed answers, and provider failures use the bounded caller-turn fallback.
- Pending classification never blocks the STT receive loop.
- Paused playback and pending decisions suppress inactivity check-ins.
- Call shutdown cancels decision timers and closes owned tasks and sockets even during a pause.
- Separate calls cannot share decisions, queued audio, response counters, or caller input.

Extend the existing activity tests for pending and paused states.
Run the existing cancellation and language tests because those paths are directly affected.

### Browser playback checks

Use deterministic fake WebSocket events and controllable audio decoding for frontend lifecycle checks.
Check that suspending playback preserves sample position and scheduled audio, and that resuming does not replay or skip segments.
Check late decode completion, repeated pause/resume messages, malformed audio headers, and cancellation followed immediately by a new response.
Confirm that the microphone remains active while the playback context is suspended.
Confirm that ending and reopening a call does not leave a suspended context, timer, or old message handler affecting the new call.

Review the call UI while testing it.
Scout's speaking state, waiting state, transcript entries, and visual audio activity must match what the caller hears.
An acknowledgment must not show a blank replacement answer or flicker into "thinking".

### Real-call checks

Exercise English, Hindi, Punjabi, and each additional supported language before claiming coverage for it.
Include mixed-language input, quiet acknowledgments, rapid corrections, speaker playback, and headphone playback.
Repeat short interruptions at the beginning, middle, and end of an answer, including after generation finishes but playback continues.
Try "okay" followed immediately by a separate "but..." fragment to check utterance merging and stale decision handling.

Verify that no canceled audio is audible after a new response begins.
Verify that temporary pauses resume the same explanation without repetition or lost words.
Do not report the feature as working from backend tests alone.

## Timing and observability

Trace the voice decision separately from retrieval and attach it to the current call's trace.
Record utterance and response IDs, decision choice, fallback reason, request duration, model, returned probabilities/confidence, and cancellation outcome.
Keep API credentials out of all events, browser state, and traces.
Follow the existing project's handling of conversation text instead of adding duplicate raw transcript logs.

Measure these separately:

- Speech onset to temporary playback pause.
- Speech end to final STT transcript.
- Final transcript to Jev result or fallback.
- Final transcript to permanent interruption or acknowledgment resume.
- Accepted caller turn to the new response's first audio.
- TTS session setup time and time spent retaining audio.

Report p50 and p95 timings plus acknowledgment mistakes, missed interruptions, and fallback frequency by language.
The overall delay includes STT endpointing and network time; the classifier deadline alone is not an end-to-end latency claim.
Tune the grace period and decision timeout from these observations.
If Jev cannot meet the turn-taking budget reliably, retain the reversible playback architecture and evaluate a faster classifier before enabling the feature broadly.

## Enablement and completion criteria

Add `VOICE_INTERRUPTION_ENABLED`, `VOICE_INTERRUPTION_GRACE_MS`, and `VOICE_INTERRUPTION_TIMEOUT_MS` configuration.
Default the feature off until coordinated frontend/backend protocol changes and validation are complete.
When disabled, preserve the existing interruption behavior while retaining response isolation that prevents stale audio.
Pin a WebSocket protocol version during call setup so incompatible frontend/backend deployments fail clearly before playback begins.

Enable the feature for controlled calls first, then expand after reviewing actual accuracy and timings.
Disabling classification must still close pending decision tasks and prevent paused playback from becoming stuck.

Completion requires:

- All deterministic acceptance scenarios and lifecycle checks passing.
- Live Jev evaluation covering short interruptions, contextual answers, and mixed-language input.
- Real browser calls demonstrating acknowledgment continuation and genuine interruption handling.
- No obsolete audio crossing response boundaries and no microphone loss during a temporary pause.
- Measured timing and classification results documented with their language coverage and limitations.

## Implementation and validation record

The classifier, response ownership, reversible playback, protocol, busy-state handling, and lifecycle protections are implemented.
The setup instructions and optional feature flag are documented in `README.md` and `.env.example`.

The Python verification suite passes 108 tests, including classifier decisions, timeouts, short answers, overlapping fragments, cancellation races, provider failures, and separate calls.
The deterministic playback suite passes nine tests.
The frontend production build passed.

Native Chrome checks used its real Web Audio implementation and a synthetic microphone, with simulated server events.
They confirmed that paused playback preserves its timeline, microphone frames continue during a pause, acknowledgments create no new answer, obsolete audio/text are ignored, and ending/reopening a call closes old contexts and tracks.

A live Jev sample covered 13 English, Hindi, Punjabi, and mixed-language examples.
An answer-policy guard prevents a listening classification from swallowing an answer when Scout has requested one.

A controlled integration check used real Sarvam realtime STT, Sarvam streaming TTS, and Jev with synthetic caller speech and a scripted answer agent.
"Okay" continued response 1, "no" created response 2, and "what" created response 3.
This check exposed and verified the fix for punctuation-only synthesis fragments rejected by Sarvam.

These checks establish the implementation and controlled behavior, including real provider integration.
They do not establish all-language accuracy, performance percentiles, or live human microphone behavior across devices.
Broader call evaluation remains part of opt-in rollout rather than a claim of completed coverage.
