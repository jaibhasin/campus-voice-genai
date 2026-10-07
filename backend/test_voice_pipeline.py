import asyncio
import base64
import io
import json
import unittest
import wave
from unittest.mock import AsyncMock, patch

from backend import voice_pipeline as voice_pipeline_module
from backend.voice_activity import CHECK_INS, VoiceActivity
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
    async def test_consecutive_final_transcripts_do_not_stop_stt_after_cancellation(self):
        events = [type("RealtimeTranscriptFinal", (), {
            "text": text, "language": "en-IN", "language_confidence": 0.99,
        })() for text in ("First question", "Second question", "Third question")]
        answered = asyncio.Event()
        calls = []

        class Agent:
            async def astream(self, text, **kwargs):
                calls.append(text)
                answered.set()
                yield {"type": "done"}

        class Browser(FakeBrowserWebSocket):
            def __init__(self):
                super().__init__()
                self.started = False

            async def receive(self):
                if not self.started:
                    self.started = True
                    return {"text": json.dumps({"type": "start_call"})}
                await answered.wait()
                return {"text": json.dumps({"type": "end_call"})}

        browser = Browser()
        client = FakeSarvamClient(FakeSttSocket(events), FakeTtsSocket())
        with patch.object(voice_pipeline_module, "sarvam_client", client), patch.object(
            voice_pipeline_module.socket, "getaddrinfo", return_value=[],
        ):
            await asyncio.wait_for(voice_pipeline_module.voice_pipeline(browser, Agent()), 1)
        self.assertEqual([msg["text"] for msg in browser.sent_json if msg["type"] == "transcript"], [event.text for event in events])
        self.assertEqual(calls, ["Third question"])

    async def test_check_in_waits_until_browser_finishes_playback(self):
        audio_sent, checked_in = asyncio.Event(), asyncio.Event()
        tts = FakeTtsSocket(events=[
            AudioOutput(data=AudioOutputData(
                content_type="audio/wav", audio=base64.b64encode(b"\x01\x02").decode("ascii"),
            )),
            EventResponse(data=EventResponseData(event_type="final")),
        ])
        self_test = self

        class Browser(FakeBrowserWebSocket):
            def __init__(self):
                super().__init__()
                self.step = 0

            async def send_bytes(self, message):
                audio_sent.set()

            async def send_json(self, message):
                await super().send_json(message)
                if message["type"] == "check_in":
                    checked_in.set()

            async def receive(self):
                self.step += 1
                if self.step == 1:
                    return {"text": json.dumps({"type": "start_call"})}
                if self.step == 2:
                    await audio_sent.wait()
                    return {"text": json.dumps({"type": "playback_started"})}
                if self.step == 3:
                    with self_test.assertRaises(TimeoutError):
                        await asyncio.wait_for(checked_in.wait(), 0.05)
                    return {"text": json.dumps({"type": "playback_done"})}
                await checked_in.wait()
                return {"text": json.dumps({"type": "end_call"})}

        original_wait = VoiceActivity.wait_for_idle
        async def short_wait(activity):
            await original_wait(activity, seconds=0.01)

        browser = Browser()
        with patch.object(voice_pipeline_module, "sarvam_client", FakeSarvamClient(FakeSttSocket(), tts)), patch.object(
            voice_pipeline_module.socket, "getaddrinfo", return_value=[],
        ), patch.object(VoiceActivity, "wait_for_idle", short_wait):
            await asyncio.wait_for(voice_pipeline_module.voice_pipeline(browser, object()), 2)
        self.assertIn({"type": "tts_done"}, browser.sent_json)
        self.assertIn({"type": "check_in", "text": CHECK_INS["en-IN"], "language_code": "en-IN"}, browser.sent_json)

    async def test_punjabi_check_in_waits_for_answer_and_never_cancels_it(self):
        started, release, checked_in, spoken = (asyncio.Event() for _ in range(4))
        tts = FakeTtsSocket()
        cancelled = []
        language_event = type("RealtimeTranscriptFinal", (), {
            "text": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ", "language": "pa-IN", "language_confidence": 0.99,
        })()

        class Agent:
            async def astream(self, text, **kwargs):
                started.set()
                try:
                    await release.wait()
                    yield {"type": "token", "content": "ਪੰਜਾਬੀ ਜਵਾਬ"}
                    yield {"type": "done"}
                except asyncio.CancelledError:
                    cancelled.append(True)
                    raise

        class Browser(FakeBrowserWebSocket):
            def __init__(self):
                super().__init__()
                self.step = 0

            async def send_json(self, message):
                await super().send_json(message)
                if message["type"] == "check_in":
                    checked_in.set()

            async def receive(self):
                self.step += 1
                if self.step == 1:
                    return {"text": json.dumps({"type": "start_call"})}
                if self.step == 2:
                    await started.wait()
                    return {"text": json.dumps({"type": "tts", "text": "English interruption"})}
                with self_test.assertRaises(TimeoutError):
                    await asyncio.wait_for(checked_in.wait(), 0.05)
                release.set()
                await checked_in.wait()
                await spoken.wait()
                return {"text": json.dumps({"type": "end_call"})}

        async def flush():
            await tts.events.put(EventResponse(data=EventResponseData(event_type="final")))
            if tts.convert.await_count > 1:
                spoken.set()

        original_wait = VoiceActivity.wait_for_idle
        async def short_wait(activity):
            await original_wait(activity, seconds=0.01)

        self_test = self
        browser = Browser()
        tts.flush.side_effect = flush
        with patch.object(voice_pipeline_module, "sarvam_client", FakeSarvamClient(FakeSttSocket([language_event]), tts)), patch.object(
            voice_pipeline_module.socket, "getaddrinfo", return_value=[],
        ), patch.object(VoiceActivity, "wait_for_idle", short_wait):
            await asyncio.wait_for(voice_pipeline_module.voice_pipeline(browser, Agent()), 2)
        self.assertEqual(cancelled, [])
        texts = [call.args[0] for call in tts.convert.await_args_list]
        self.assertEqual(texts[0], "ਪੰਜਾਬੀ ਜਵਾਬ")
        self.assertEqual(" ".join(texts[1:]), CHECK_INS["pa-IN"])
        self.assertIn({"type": "check_in", "text": CHECK_INS["pa-IN"], "language_code": "pa-IN"}, browser.sent_json)

    async def test_stable_language_is_shared_by_agent_and_serialized_tts(self):
        turns = [
            ("What are the hostel fees?", "en-IN", 0.99),
            ("Tell me about hostel charges", "hi-IN", 0.01),
            ("Yes", "hi-IN", 0.99),
            ("मुझे हॉस्टल के बारे में बताओ", "hi-IN", 0.99),
            ("मुझे एडमिशन के बारे में बताओ", "hi-IN", 0.99),
            ("Please respond in Punjabi", "en-IN", 0.99),
        ]
        handled = asyncio.Queue()
        flushed = asyncio.Event()

        class Stt(FakeSttSocket):
            async def __aiter__(self):
                for text, language, confidence in turns:
                    yield type("RealtimeTranscriptFinal", (), {
                        "text": text, "language": language, "language_confidence": confidence,
                    })()
                    await handled.get()
                await asyncio.Event().wait()

        class Agent:
            def __init__(self):
                self.languages = []

            async def astream(self, text, **kwargs):
                self.languages.append(kwargs["config"]["configurable"]["response_language"])
                yield {"type": "token", "content": "Synthetic response"}
                yield {"type": "done", "full_content": "Synthetic response"}
                await handled.put(True)

        class Browser(FakeBrowserWebSocket):
            def __init__(self):
                super().__init__()
                self.started = False

            async def receive(self):
                if not self.started:
                    self.started = True
                    return {"text": json.dumps({"type": "start_call"})}
                await flushed.wait()
                return {"text": json.dumps({"type": "end_call"})}

        agent, browser, tts = Agent(), Browser(), FakeTtsSocket()
        order = []
        async def configure(**kwargs):
            order.append(("language", kwargs["target_language_code"]))

        async def convert(text):
            order.append(("text", text))

        async def flush():
            if len(agent.languages) == len(turns):
                flushed.set()

        tts.configure.side_effect = configure
        tts.convert.side_effect = convert
        tts.flush.side_effect = flush
        with patch.object(voice_pipeline_module, "sarvam_client", FakeSarvamClient(Stt(), tts)), patch.object(
            voice_pipeline_module.socket, "getaddrinfo", return_value=[],
        ):
            await asyncio.wait_for(voice_pipeline_module.voice_pipeline(browser, agent), 2)
        expected = ["en-IN", "en-IN", "en-IN", "en-IN", "hi-IN", "pa-IN"]
        self.assertEqual(agent.languages, expected)
        self.assertEqual([event["language_code"] for event in browser.sent_json if event["type"] == "transcript"], expected)
        self.assertEqual([code for kind, code in order if kind == "language"], ["en-IN", "hi-IN", "pa-IN"])
        self.assertEqual(order[-2:], [("language", "pa-IN"), ("text", "Synthetic response")])

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
        await self.check_call_provider("decisions")

    async def test_passes_selected_jev_provider_to_voice_agent(self):
        await self.check_call_provider("jev")

    async def check_call_provider(self, provider):
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
                voice_pipeline_module.voice_pipeline(browser, agent, provider),
                timeout=1,
            )

        self.assertEqual(
            agent.calls,
            [
                (
                    "Hello",
                    {"config": {"configurable": {
                        "thread_id": "voice-call-123", "response_language": "en-IN",
                        "retrieval_provider": provider,
                    }}},
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
