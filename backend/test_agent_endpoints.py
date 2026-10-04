import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from Agent.prompts.prompts import voice_assistant_system_prompt
from Agent.test_graph import make_agent
from Agent.test_retrieval import answer, read_first
from backend import main


def events(response):
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


class AgentEndpointTests(unittest.TestCase):
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
