import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from Agent.prompts.prompts import voice_assistant_system_prompt
from Agent.retrieval import Retriever
from Agent.test_graph import make_agent
from Agent.test_retrieval import ScriptedClient, answer, documents, read_first
from backend import main


def events(response):
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


class AgentEndpointTests(unittest.TestCase):
    def test_chat_and_voice_default_to_decisions_and_allow_all_providers(self):
        for endpoint in ("/api/chat", "/api/chat/voice"):
            for provider in (None, "decisions", "jev", "llm_batch"):
                with self.subTest(endpoint=endpoint, provider=provider):
                    agent = Mock()
                    agent.stream.return_value = iter([{"type": "done"}])
                    body = {"message": "Hello", "thread_id": "selection"}
                    if provider is not None:
                        body["retrieval_provider"] = provider
                    with patch.object(main, "agent_instance", agent), patch.object(
                        main, "voice_agent_instance", agent
                    ):
                        response = TestClient(main.app).post(endpoint, json=body)
                    self.assertEqual(response.status_code, 200)
                    agent.stream.assert_called_once_with("Hello", config={"configurable": {
                        "thread_id": "selection", "retrieval_provider": provider or "decisions",
                    }})

    def test_invalid_chat_provider_is_rejected_before_agent_call(self):
        agent = Mock()
        with patch.object(main, "agent_instance", agent):
            response = TestClient(main.app).post("/api/chat", json={
                "message": "Hello", "retrieval_provider": "invented",
            })
        self.assertEqual(response.status_code, 422)
        agent.stream.assert_not_called()

    def test_voice_socket_passes_provider_before_connecting_to_speech_services(self):
        for query, provider in (("", "decisions"), ("?retrieval_provider=jev", "jev"), ("?retrieval_provider=llm_batch", "llm_batch")):
            with self.subTest(provider=provider):
                async def pipeline(socket, agent, selected, expected=provider):
                    self.assertEqual(selected, expected)
                    await socket.accept()
                    await socket.close()

                with (
                    patch("backend.voice_pipeline.voice_pipeline", side_effect=pipeline) as call,
                    TestClient(main.app).websocket_connect("/api/voice/ws" + query),
                ):
                    pass
                call.assert_awaited_once()

    def test_stt_upload_passes_bytes_to_sdk_outside_event_loop(self):
        def transcribe(**kwargs):
            self.assertRaises(RuntimeError, asyncio.get_running_loop)
            self.assertEqual(kwargs["file"], ("sample.wav", b"audio", "audio/wav"))
            return SimpleNamespace(transcript="Hello", language_code="unknown")

        client = Mock()
        client.speech_to_text.transcribe.side_effect = transcribe
        with patch.object(main, "sarvam_client", client):
            response = TestClient(main.app).post(
                "/api/stt", files={"file": ("sample.wav", b"audio", "audio/wav")}
            )
        self.assertEqual(
            response.json(), {"transcript": "Hello", "language_code": "en-IN"}
        )
        client.speech_to_text.transcribe.assert_called_once()

    def test_tts_sdk_runs_outside_event_loop_and_preserves_audio(self):
        def convert(**kwargs):
            self.assertRaises(RuntimeError, asyncio.get_running_loop)
            self.assertEqual(kwargs["text"], "Hello")
            return SimpleNamespace(audios=["encoded-audio"])

        client = Mock()
        client.text_to_speech.convert.side_effect = convert
        with patch.object(main, "sarvam_client", client):
            response = TestClient(main.app).post("/api/tts", json={"text": "Hello"})
        self.assertEqual(response.json(), {"audio_base64": "encoded-audio"})
        client.text_to_speech.convert.assert_called_once()

    def test_shutdown_flushes_traces_after_closing_agents(self):
        chat, voice = AsyncMock(), AsyncMock()
        with (
            patch.object(main, "Agent", side_effect=[chat, voice]),
            patch.object(main, "SarvamAI"),
            patch.object(main, "wait_for_all_tracers") as flush,
            TestClient(main.app),
        ):
            flush.assert_not_called()
        chat.aclose.assert_awaited_once()
        voice.aclose.assert_awaited_once()
        flush.assert_called_once_with()

    def test_chat_endpoint_streams_retrieval_progress_then_answer(self):
        agent, jev, model = make_agent(
            [read_first, read_first, answer("ready_to_answer")]
        )
        with patch.object(main, "agent_instance", agent):
            response = TestClient(main.app).post(
                "/api/chat",
                json={
                    "message": "Hostel fees?",
                    "thread_id": "endpoint-chat",
                    "retrieval_provider": "jev",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.headers["content-type"].startswith("text/event-stream")
        )
        emitted = events(response)
        self.assertEqual(emitted[0]["type"], "tool_call")
        self.assertEqual(emitted[-1]["type"], "done")
        self.assertEqual(emitted[-1]["full_content"], "Grounded answer.")
        self.assertEqual(len(jev.calls), 3)
        self.assertEqual(len(model.calls), 1)

    def test_voice_endpoint_uses_evidence_only_voice_prompt(self):
        agent, _jev, model = make_agent(
            [answer("ready_to_answer")], system_prompt=voice_assistant_system_prompt
        )
        agent.retrievers["decisions"] = Retriever(
            documents(), ScriptedClient([answer("ready_to_answer")])
        )
        with patch.object(main, "voice_agent_instance", agent):
            response = TestClient(main.app).post(
                "/api/chat/voice",
                json={
                    "message": "Hello",
                    "thread_id": "endpoint-voice",
                },
            )
        self.assertEqual(events(response)[-1]["full_content"], "Grounded answer.")
        self.assertIn("voice conversation", model.calls[0][0].content)
        self.assertIn("no retrieval tools", model.calls[0][0].content)
        self.assertNotIn("You have 3 tools", model.calls[0][0].content)
