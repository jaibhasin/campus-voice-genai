"""Live Sarvam phone-codec probe; never places a telephone call."""

import asyncio
import base64
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sarvamai import AsyncSarvamAI
from sarvamai.types.realtime_audio_input import RealtimeAudioInput

from backend.voice_response import VoiceResponse, synthesize_response
from backend.voice_transport import PHONE_AUDIO


async def probe(progress=lambda _stage: None):
    key = os.getenv("SARVAM_API_KEY", "")
    if not key:
        raise ValueError("SARVAM_API_KEY is required")
    client = AsyncSarvamAI(api_subscription_key=key)
    response = VoiceResponse(1, "en-IN")
    audio = bytearray()
    completed = False

    async def output(chunk):
        if chunk.encoding != "mulaw" or chunk.sample_rate != 8000:
            raise ValueError("Unexpected phone output format")
        if not audio:
            progress("tts_audio_received")
        audio.extend(chunk.audio)
        if len(audio) > 160000:
            raise ValueError("Probe retained more than twenty seconds of audio")

    async def event(message):
        nonlocal completed
        completed |= message["type"] == "tts_done"

    async def producer():
        await response.put_text("Hello, I would like to know about hostel fees.")
        await response.text_queue.put(None)

    progress("tts_started")
    async with asyncio.timeout(45):
        await synthesize_response(response, client, event, output, lambda _: None, producer, audio_format=PHONE_AUDIO)
    if not completed or not audio or audio[:4] == b"RIFF":
        raise ValueError("Phone synthesis did not produce complete raw audio")
    progress("tts_completed")
    async with client.speech_to_text_realtime_streaming.connect(
        language_code="auto", model="saaras:v3-realtime", stream_type="fast",
        mode="transcribe", encoding="mulaw", sample_rate="8000", endpointing="vad",
        silence_duration_ms="500",
    ) as stt:
        progress("stt_connected")
        async def send():
            # Replay the synthetic fixture at real-time pace, with silence for VAD.
            fixture = bytes(audio) + b"\xff" * 24000
            for offset in range(0, len(fixture), 160):
                await stt.send_realtime_audio_input(RealtimeAudioInput(
                    audio=base64.b64encode(fixture[offset:offset + 160]).decode("ascii"),
                ))
                await asyncio.sleep(0.02)

        async def recognize():
            seen = set()
            async for message in stt:
                name = type(message).__name__
                if name not in seen:
                    seen.add(name)
                    progress("stt_" + name)
                if type(message).__name__ == "RealtimeTranscriptFinal" and message.text.strip():
                    text = message.text.lower()
                    return "hostel" in text and "fee" in text
                if type(message).__name__ == "RealtimeError" and message.is_fatal:
                    raise RuntimeError("Phone recognition provider failed")
            return False

        sending = asyncio.create_task(send())
        try:
            recognized = await asyncio.wait_for(recognize(), timeout=30)
        finally:
            sending.cancel()
            await asyncio.gather(sending, return_exceptions=True)
    if not recognized:
        raise RuntimeError("Phone transcript did not recognize the fixture's hostel-fee question")
    return {"tts_complete": completed, "audio_bytes": len(audio), "encoding": "mulaw",
            "sample_rate": 8000, "stt_final_received": recognized}


def main():
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    stage = "initializing"

    def progress(value):
        nonlocal stage
        stage = value
        print(json.dumps({"stage": stage}), flush=True)

    try:
        result = asyncio.run(probe(progress))
    except Exception as error:  # noqa: BLE001 - Sanitize external provider errors in CLI output.
        print(json.dumps({"ok": False, "stage": stage, "error_type": type(error).__name__}))
        return 1
    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
