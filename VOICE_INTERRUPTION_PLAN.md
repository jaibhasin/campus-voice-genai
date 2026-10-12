# Voice interruption classification plan

Status: planned; feature implementation has not started.
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

Start with a 350 ms playback grace period and a 1,000 ms total classifier deadline after the final transcript.
These are initial tuning values, not measured service guarantees.
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
