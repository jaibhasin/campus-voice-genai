"""
WebSocket-based voice pipeline for Scout.
Bridges browser audio <-> Sarvam streaming STT <-> Agent <-> Sarvam streaming TTS.

The Agent instance must be passed in from the caller (e.g. main.py) so that
boot-time creation stays in one place.
"""

import asyncio
import json
import base64
import os
import socket
import struct
import traceback
import uuid

from fastapi import WebSocket, WebSocketDisconnect
from sarvamai import AsyncSarvamAI
from sarvamai.types.realtime_audio_input import RealtimeAudioInput
from sarvamai.types.audio_output import AudioOutput

from backend.voice_language import VoiceLanguage
from backend.voice_activity import CHECK_INS, VoiceActivity

# ── Config ──
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
sarvam_client = AsyncSarvamAI(api_subscription_key=SARVAM_API_KEY)


def pcm16_to_wav(pcm_audio: bytes, sample_rate: int = 22050) -> bytes:
    """Wrap mono PCM16 bytes as a complete WAV file for browser decoding."""
    data_size = len(pcm_audio)
    byte_rate = sample_rate * 2
    return b"".join((
        b"RIFF",
        struct.pack("<I", 36 + data_size),
        b"WAVEfmt ",
        struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, byte_rate, 2, 16),
        b"data",
        struct.pack("<I", data_size),
        pcm_audio,
    ))


async def voice_pipeline(websocket: WebSocket, voice_agent):
    """Handle a single voice call session over WebSocket.

    Args:
        websocket: The FastAPI WebSocket for this session.
        voice_agent: An Agent instance (must have an async ``astream`` method).
    """
    await websocket.accept()

    stt_ws = None
    tts_ws = None
    stt_connection = None
    tts_connection = None
    stt_task = None
    agent_task = None
    tts_send_task = None
    tts_recv_task = None
    inactivity_task = None
    language = VoiceLanguage()
    activity = VoiceActivity()
    thread_id = str(uuid.uuid4())

    try:
        # ── 1. Open Sarvam STT realtime streaming connection ──
        print("[VOICE] Connecting to Sarvam STT...")
        try:
            await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(
                    "api.sarvam.ai",
                    443,
                    type=socket.SOCK_STREAM,
                ),
                timeout=5,
            )
            print("[VOICE] Sarvam hostname resolved")
        except Exception as exc:
            print(f"[VOICE] Sarvam DNS preflight failed: {exc!r}")
            raise

        stt_error = None
        for attempt in range(1, 4):
            try:
                stt_connection = sarvam_client.speech_to_text_realtime_streaming.connect(
                    language_code="auto",
                    model="saaras:v3-realtime",
                    stream_type="fast",       # lowest latency
                    mode="transcribe",
                    encoding="linear16",      # PCM16 signed 16-bit
                    sample_rate="16000",
                    endpointing="vad",        # Sarvam handles VAD
                )
                stt_ws = await asyncio.wait_for(
                    stt_connection.__aenter__(),
                    timeout=15,
                )
                break
            except Exception as exc:
                stt_error = exc
                print(f"[VOICE] Sarvam STT attempt {attempt}/3 failed: {exc!r}")
                if stt_connection:
                    try:
                        await stt_connection.__aexit__(None, None, None)
                    except Exception:
                        pass
                    stt_connection = None
                if attempt < 3:
                    await asyncio.sleep(2 ** (attempt - 1))
        if stt_ws is None:
            raise stt_error
        print("[VOICE] Sarvam STT connected")

        # ── 2. Open Sarvam TTS streaming connection ──
        print("[VOICE] Connecting to Sarvam TTS...")
        tts_connection = sarvam_client.text_to_speech_streaming.connect(
            model="bulbul:v3",
            send_completion_event="true",
        )
        tts_ws = await tts_connection.__aenter__()
        await tts_ws.configure(
            target_language_code="en-IN",
            speaker="shubh",
            output_audio_codec="wav",
            speech_sample_rate=22050,
        )
        print("[VOICE] Sarvam TTS connected and configured")
        await websocket.send_json({"type": "voice_ready"})
        print("[VOICE] Browser marked ready")

        # ── Queues ──
        agent_text_queue: asyncio.Queue = asyncio.Queue()   # agent tokens → TTS sender

        # ── STT event handler ─────────────────────────────────────────────
        async def handle_stt_events():
            """Listen for Sarvam STT events and trigger agent on final transcript."""
            try:
                async for event in stt_ws:
                    event_type = type(event).__name__
                    if event_type in {
                        "RealtimeTranscriptPartial", "RealtimeTranscriptFinal",
                        "RealtimeVadSpeechStart", "RealtimeVadSpeechEnd",
                    }:
                        activity.touch()

                    if event_type == "RealtimeTranscriptPartial":
                        await websocket.send_json({
                            "type": "partial_transcript",
                            "text": getattr(event, "text", ""),
                        })

                    elif event_type == "RealtimeTranscriptFinal":
                        transcript = getattr(event, "text", "").strip()
                        activity.user_speaking = False
                        activity.awaiting_transcript = False
                        if transcript.strip():
                            activity.response_pending = True
                            previous_language = language.current
                            response_language = language.observe(
                                transcript,
                                getattr(event, "language", None),
                                getattr(event, "language_confidence", None),
                            )
                            await websocket.send_json({
                                "type": "transcript",
                                "text": transcript,
                                "language_code": response_language,
                            })

                            # Cancel previous agent (user barge-in)
                            nonlocal agent_task
                            if agent_task and not agent_task.done():
                                agent_task.cancel()
                                await agent_task

                            # Signal TTS handler to discard old response
                            await agent_text_queue.put("RESET")
                            if response_language != previous_language:
                                await agent_text_queue.put(("language", response_language))

                            agent_task = asyncio.create_task(
                                run_agent(transcript, response_language)
                            )

                    elif event_type == "RealtimeVadSpeechStart":
                        activity.user_speaking = True
                        await websocket.send_json({"type": "vad_speech_start"})

                    elif event_type == "RealtimeVadSpeechEnd":
                        activity.user_speaking = False
                        # Wait for the final transcript and answer before idle.
                        activity.awaiting_transcript = True
                        await websocket.send_json({"type": "vad_speech_end"})

                    elif event_type == "RealtimeSessionEnd":
                        break

            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[STT Event Error] {e}")

        # ── Agent runner ──────────────────────────────────────────────────
        async def run_agent(text: str, response_language: str):
            """Run the LangGraph agent and push text tokens to the TTS queue."""
            activity.answering = True
            try:
                async for event in voice_agent.astream(
                    text,
                    config={"configurable": {
                        "thread_id": thread_id,
                        "response_language": response_language,
                    }},
                ):
                    activity.touch()
                    if event.get("type") == "token":
                        content = event["content"]
                        await websocket.send_json({
                            "type": "agent_token",
                            "content": content,
                        })
                        await agent_text_queue.put(content)
                    elif event.get("type") == "done":
                        await websocket.send_json({
                            "type": "agent_done",
                            "full_content": event.get("full_content", ""),
                        })
                        await agent_text_queue.put(None)  # signal end
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[Agent Error] {e}")
                await agent_text_queue.put(None)
            finally:
                activity.answering = False
                activity.touch()

        # ── TTS text sender (sends sentences as they form) ────────────────
        async def handle_tts_send():
            """Read tokens from agent_text_queue, form sentences, send to TTS."""
            buffer = ""
            try:
                while True:
                    token = await agent_text_queue.get()

                    if isinstance(token, tuple) and token[0] == "language":
                        await tts_ws.configure(
                            target_language_code=token[1],
                            speaker="shubh",
                            output_audio_codec="wav",
                            speech_sample_rate=22050,
                        )
                        continue

                    # Barge-in: user interrupted — discard current buffer
                    if token == "RESET":
                        buffer = ""
                        continue

                    if token is None:
                        if buffer.strip():
                            await tts_ws.convert(buffer.strip())
                            buffer = ""
                        await tts_ws.flush()
                        continue

                    buffer += token
                    # Split on common sentence boundaries
                    for sep in (". ", "! ", "? ", "। "):
                        parts = buffer.split(sep)
                        if len(parts) > 1:
                            for p in parts[:-1]:
                                if p.strip():
                                    await tts_ws.convert(p.strip() + sep.strip())
                            buffer = parts[-1]
                            break  # only split on the first matched separator

            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[TTS Send Error] {e}")

        # ── TTS audio collector (listens for AudioOutput events) ──────────
        async def handle_tts_recv():
            """Listen for TTS audio responses and forward to browser."""
            try:
                while True:
                    tts_event = await tts_ws.recv()
                    if isinstance(tts_event, AudioOutput):
                        activity.touch()
                        audio_chunk = base64.b64decode(tts_event.data.audio)
                        if audio_chunk.startswith(b"RIFF"):
                            audio_chunk = audio_chunk[44:]
                        if audio_chunk:
                            activity.playback_active = True
                            await websocket.send_bytes(pcm16_to_wav(audio_chunk))
                    elif type(tts_event).__name__ == "EventResponse":
                        if tts_event.data.event_type == "final":
                            activity.response_pending = False
                            activity.touch()
                            await websocket.send_json({"type": "tts_done"})
                    elif type(tts_event).__name__ == "ErrorResponse":
                        print(f"[TTS Error Response] {tts_event}")
                    # Non-audio events are silently ignored
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[TTS Recv Error] {e}")

        async def handle_inactivity():
            while True:
                await activity.wait_for_idle()
                # Never substitute English for an unsupported check-in language.
                text = CHECK_INS.get(language.current)
                if text is None:
                    continue
                activity.response_pending = True
                activity.touch()
                await websocket.send_json({
                    "type": "check_in", "text": text,
                    "language_code": language.current,
                })
                await agent_text_queue.put(text)
                await agent_text_queue.put(None)

        # ── Start STT event listener immediately ──
        stt_task = asyncio.create_task(handle_stt_events())

        # ── Main loop: receive audio from browser, forward to Sarvam STT ──
        while True:
            message = await websocket.receive()

            if "bytes" in message:
                # Binary PCM16 audio frames from browser → Sarvam STT
                await stt_ws.send_realtime_audio_input(
                    RealtimeAudioInput(
                        audio=base64.b64encode(message["bytes"]).decode("utf-8")
                    )
                )
            elif "text" in message:
                data = json.loads(message["text"])
                if data.get("type") == "start_call":
                    client_thread_id = data.get("thread_id")
                    if isinstance(client_thread_id, str) and client_thread_id.strip():
                        thread_id = client_thread_id
                    if activity.started:
                        continue
                    activity.started = True
                    activity.touch()
                    # Start TTS pipeline once the call begins
                    tts_send_task = asyncio.create_task(handle_tts_send())
                    tts_recv_task = asyncio.create_task(handle_tts_recv())
                    inactivity_task = asyncio.create_task(handle_inactivity())
                elif data.get("type") in {"playback_started", "playback_done"}:
                    activity.playback_active = data["type"] == "playback_started"
                    activity.touch()
                elif data.get("type") == "tts":
                    # Direct speech must never interrupt an active conversation.
                    text = data.get("text", "").strip()
                    if text and tts_ws and activity.idle:
                        activity.response_pending = True
                        activity.touch()
                        await agent_text_queue.put("RESET")
                        await agent_text_queue.put(text)
                        await agent_text_queue.put(None)
                elif data.get("type") == "end_call":
                    break

    except WebSocketDisconnect:
        print("[Voice Pipeline] Client disconnected")
    except Exception as e:
        print(f"[Voice Pipeline Error] {e!r}")
        traceback.print_exc()
        try:
            await websocket.send_json({
                "type": "voice_error",
                "message": "Could not connect to the voice service. Please try again.",
            })
        except Exception:
            pass
    finally:
        # Cancel all tasks
        tasks = list(filter(None, [stt_task, agent_task, tts_send_task, tts_recv_task, inactivity_task]))
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Exit SDK-managed async connections.
        for connection in (stt_connection, tts_connection):
            if connection:
                try:
                    await connection.__aexit__(None, None, None)
                except Exception:
                    pass
