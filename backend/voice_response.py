"""One response owns its generation, synthesis socket, and bounded text queue."""

import asyncio
import base64
import re
import struct
from dataclasses import dataclass, field

from sarvamai.types.audio_output import AudioOutput


PROTOCOL_VERSION = 2


def pcm16_to_wav(pcm_audio: bytes, sample_rate: int = 22050) -> bytes:
    """Wrap mono PCM16 bytes as a complete WAV file for browser decoding."""
    size = len(pcm_audio)
    return b"".join((
        b"RIFF", struct.pack("<I", 36 + size), b"WAVEfmt ",
        struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16),
        b"data", struct.pack("<I", size), pcm_audio,
    ))


@dataclass
class VoiceResponse:
    response_id: int
    language: str
    text_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=32))
    playable: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    cancelled: bool = False
    generated_text: str = ""
    audio_sent: bool = False
    playback_complete: bool = False

    def __post_init__(self):
        self.playable.set()

    async def put_text(self, text):
        # Bound token size as well as queue length, including oversized tool output.
        for offset in range(0, len(text), 400):
            await self.text_queue.put(text[offset:offset + 400])

    async def cancel(self):
        # Invalidate before awaiting: a collector already holding audio cannot send it.
        self.cancelled = True
        self.playable.set()
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        while not self.text_queue.empty():
            self.text_queue.get_nowait()


async def synthesize_response(response, client, send_json, send_bytes, on_audio, producer):
    """Never relabel provider output with a successor response's ID.

    The receiver retains at most one provider packet while paused and stops reading
    the socket, applying transport backpressure. The sender stops at the same gate;
    bounded token queues then slow generation instead of dropping middle segments.
    """
    connection = client.text_to_speech_streaming.connect(
        model="bulbul:v3", send_completion_event="true",
    )
    children = []
    try:
        tts = await asyncio.wait_for(connection.__aenter__(), timeout=15)
        await tts.configure(
            target_language_code=response.language, speaker="shubh",
            output_audio_codec="wav", speech_sample_rate=22050,
        )

        async def convert(text):
            await response.playable.wait()
            if not response.cancelled:
                await tts.convert(text)

        async def sender():
            buffer = ""
            while not response.cancelled:
                token = await response.text_queue.get()
                if token is None:
                    if buffer.strip():
                        await convert(buffer.strip())
                    await response.playable.wait()
                    if not response.cancelled:
                        await tts.flush()
                    return
                buffer += token
                while buffer:
                    boundary = re.search(r"[.!?।](?:\s|$)", buffer)
                    cut = boundary.end() if boundary else (400 if len(buffer) >= 400 else 0)
                    if not cut:
                        break
                    sentence, buffer = buffer[:cut].strip(), buffer[cut:]
                    if sentence:
                        await convert(sentence)

        async def receiver():
            while not response.cancelled:
                # Provider silence cannot leave response_pending stuck indefinitely.
                await response.playable.wait()
                event = await asyncio.wait_for(tts.recv(), timeout=45)
                await response.playable.wait()
                if response.cancelled:
                    return
                if isinstance(event, AudioOutput):
                    encoded = event.data.audio
                    if len(encoded) > 4 * 1024 * 1024:
                        raise ValueError("Voice provider audio packet exceeds retention bound")
                    audio = base64.b64decode(encoded)
                    if audio.startswith(b"RIFF"):
                        audio = audio[44:]
                    if audio:
                        response.audio_sent = True
                        response.playback_complete = False
                        on_audio(response)
                        packet = struct.pack(
                            ">BI", PROTOCOL_VERSION, response.response_id,
                        ) + pcm16_to_wav(audio)
                        await send_bytes(packet)
                elif type(event).__name__ == "EventResponse" and event.data.event_type == "final":
                    await send_json({"type": "tts_done", "response_id": response.response_id})
                    return
                elif type(event).__name__ == "ErrorResponse":
                    raise RuntimeError("Voice synthesis provider rejected response")

        children = [asyncio.create_task(producer()), asyncio.create_task(sender()), asyncio.create_task(receiver())]
        # Fail promptly if one side dies instead of waiting on an abandoned queue.
        done, pending = await asyncio.wait(children, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()
        await asyncio.gather(*pending)
    finally:
        for task in children:
            if not task.done():
                task.cancel()
        await asyncio.gather(*children, return_exceptions=True)
        try:
            await connection.__aexit__(None, None, None)
        except Exception:
            pass
