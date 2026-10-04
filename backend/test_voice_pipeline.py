import asyncio
import base64
import io
import json
import unittest
import wave
from unittest.mock import AsyncMock, patch

from backend import voice_pipeline as voice_pipeline_module
from sarvamai.types.audio_output import AudioOutput
from sarvamai.types.audio_output_data import AudioOutputData
from sarvamai.types.event_response import EventResponse
from sarvamai.types.event_response_data import EventResponseData


class FakeConnection:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return None


class FakeSttSocket:
    def __init__(self, events=None):
        self.events = events or []
        self.start_listening = AsyncMock(
            side_effect=AssertionError("start_listening blocks until the socket closes")
        )

    async def __aiter__(self):
        for event in self.events:
            yield event
        await asyncio.Event().wait()
        yield


class FakeTtsSocket:
    def __init__(self, events=None):
        self.events = asyncio.Queue()
        for event in events or []:
            self.events.put_nowait(event)
        self.start_listening = AsyncMock(
            side_effect=AssertionError("start_listening blocks until the socket closes")
        )
        self.configure = AsyncMock()
        self.convert = AsyncMock()
        self.flush = AsyncMock()

    async def recv(self):
        return await self.events.get()


class FakeStreamingService:
    def __init__(self, socket):
        self.socket = socket

    def connect(self, **_kwargs):
        return FakeConnection(self.socket)


class FakeSarvamClient:
    def __init__(self, stt_socket, tts_socket):
        self.speech_to_text_realtime_streaming = FakeStreamingService(stt_socket)
        self.text_to_speech_streaming = FakeStreamingService(tts_socket)


class FakeBrowserWebSocket:
    def __init__(self):
        self.accepted = False
        self.sent_json = []
        self.incoming = asyncio.Queue()

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        self.sent_json.append(message)

    async def send_bytes(self, message):
        pass

    async def receive(self):
        return await self.incoming.get()


class VoicePipelineConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_marks_browser_ready_without_awaiting_sdk_listener_loops(self):
        browser = FakeBrowserWebSocket()
        stt_socket = FakeSttSocket()
        tts_socket = FakeTtsSocket()
        client = FakeSarvamClient(stt_socket, tts_socket)
        await browser.incoming.put({"text": json.dumps({"type": "end_call"})})

        with patch.object(voice_pipeline_module, "sarvam_client", client), patch.object(
            voice_pipeline_module.socket,
            "getaddrinfo",
            return_value=[],
        ):
            await asyncio.wait_for(
                voice_pipeline_module.voice_pipeline(browser, object()),
                timeout=1,
            )

        self.assertTrue(browser.accepted)
        self.assertIn({"type": "voice_ready"}, browser.sent_json)
        stt_socket.start_listening.assert_not_awaited()
        tts_socket.start_listening.assert_not_awaited()
        tts_socket.configure.assert_awaited_once()

    async def test_passes_call_thread_id_to_voice_agent(self):
        transcript_event = type(
            "RealtimeTranscriptFinal",
            (),
            {"text": "Hello", "language": "en-IN"},
        )()
        stt_socket = FakeSttSocket(events=[transcript_event])
        tts_socket = FakeTtsSocket()
        client = FakeSarvamClient(stt_socket, tts_socket)
        agent_called = asyncio.Event()

        class FakeAgent:
            def __init__(self):
                self.calls = []

            async def astream(self, text, **kwargs):
                self.calls.append((text, kwargs))
                agent_called.set()
                yield {"type": "token", "content": "Hi there"}
                yield {"type": "done", "full_content": ""}

        class CoordinatedBrowser(FakeBrowserWebSocket):
            def __init__(self):
                super().__init__()
                self.receive_count = 0

            async def receive(self):
                self.receive_count += 1
                if self.receive_count == 1:
                    return {
                        "text": json.dumps(
                            {"type": "start_call", "thread_id": "voice-call-123"}
                        )
                    }
                await asyncio.wait_for(agent_called.wait(), timeout=1)
                return {"text": json.dumps({"type": "end_call"})}

        browser = CoordinatedBrowser()
        agent = FakeAgent()

        with patch.object(voice_pipeline_module, "sarvam_client", client), patch.object(
            voice_pipeline_module.socket,
            "getaddrinfo",
            return_value=[],
        ):
            await asyncio.wait_for(
                voice_pipeline_module.voice_pipeline(browser, agent),
                timeout=1,
            )

        self.assertEqual(
            agent.calls,
            [
                (
                    "Hello",
                    {"config": {"configurable": {"thread_id": "voice-call-123"}}},
                )
            ],
        )
        self.assertIn({"type": "transcript", "text": "Hello", "language_code": "en-IN"}, browser.sent_json)
        self.assertIn({"type": "agent_token", "content": "Hi there"}, browser.sent_json)

    async def test_wraps_each_pcm_chunk_as_playable_wav_for_streaming(self):
        wav_header = b"RIFF" + (b"\x00" * 40)
        pcm_audio = b"\x01\x02\x03\x04"
        tts_socket = FakeTtsSocket(events=[
            AudioOutput(data=AudioOutputData(
                content_type="audio/wav",
                audio=base64.b64encode(wav_header).decode("ascii"),
            )),
            AudioOutput(data=AudioOutputData(
                content_type="audio/wav",
                audio=base64.b64encode(pcm_audio).decode("ascii"),
            )),
            EventResponse(data=EventResponseData(event_type="final")),
        ])
        client = FakeSarvamClient(FakeSttSocket(), tts_socket)
        audio_sent = asyncio.Event()

        class AudioBrowser(FakeBrowserWebSocket):
            def __init__(self):
                super().__init__()
                self.receive_count = 0
                self.sent_audio = []

            async def receive(self):
                self.receive_count += 1
                if self.receive_count == 1:
                    return {"text": json.dumps({"type": "start_call"})}
                await asyncio.wait_for(audio_sent.wait(), timeout=1)
                return {"text": json.dumps({"type": "end_call"})}

            async def send_bytes(self, message):
                self.sent_audio.append(message)
                audio_sent.set()

        browser = AudioBrowser()
        with patch.object(voice_pipeline_module, "sarvam_client", client), patch.object(
            voice_pipeline_module.socket,
            "getaddrinfo",
            return_value=[],
        ):
            await asyncio.wait_for(
                voice_pipeline_module.voice_pipeline(browser, object()),
                timeout=1,
            )

        self.assertEqual(len(browser.sent_audio), 1)
        with wave.open(io.BytesIO(browser.sent_audio[0]), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 22050)
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.readframes(wav_file.getnframes()), pcm_audio)


if __name__ == "__main__":
    unittest.main()
