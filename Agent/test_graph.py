import asyncio
import json
import unittest
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from Agent.graph import Agent, AgentState
from Agent.retrieval import Retriever
from Agent.test_retrieval import ScriptedClient, answer, documents, read_first


class RecordingModel(BaseChatModel):
    calls: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "recording-model"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="Grounded answer."))]
        )

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        for token in ("Grounded ", "answer."):
            yield ChatGenerationChunk(message=AIMessageChunk(content=token))

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        for chunk in self._stream(messages, stop, run_manager, **kwargs):
            yield chunk


def make_agent(script, **kwargs):
    client = ScriptedClient(script)
    model = RecordingModel()
    with patch("Agent.graph.ChatOpenAI", return_value=model):
        agent = Agent(
            "Test",
            retrieval_mode="jev",
            retriever=Retriever(documents(), client),
            **kwargs,
        )
    return agent, client, model


class GraphTests(unittest.TestCase):
    def test_long_conversation_retains_a_full_bounded_suffix(self):
        previous = "a" * 2000 + "₹" * 600 + " important follow-up detail"
        state = AgentState(
            messages=[
                HumanMessage(content=previous),
                HumanMessage(content="And hostel?"),
            ]
        )
        question, conversation = Agent._retrieval_input(state)
        self.assertEqual(question, "And hostel?")
        self.assertTrue(conversation[0]["text"].endswith("important follow-up detail"))
        self.assertGreater(len(conversation[0]["text"].encode("utf-8")), 1990)
        self.assertLessEqual(len(conversation[0]["text"].encode("utf-8")), 2000)
        self.assertTrue(conversation[0]["truncated"])

    def test_llm_called_once_after_source_retrieval_and_receives_full_evidence(self):
        agent, client, model = make_agent(
            [read_first, read_first, answer("ready_to_answer")]
        )
        events = list(
            agent.stream(
                "Hostel fees?", config={"configurable": {"thread_id": "chat-1"}}
            )
        )
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(len(client.calls), 3)
        prompt = model.calls[0][-1].content
        context = json.loads(prompt.split("\n", 1)[1])
        self.assertEqual(context["sources"][0]["text"], "Hostel fees are Rs. 50000.")
        self.assertEqual(context["sources"][0]["document"], "fees")
        self.assertEqual(context["stop_reason"], "ready_to_answer")
        self.assertEqual(events[-1]["full_content"], "Grounded answer.")
        self.assertEqual(
            len([event for event in events if event["type"] == "tool_call"]), 2
        )
        self.assertEqual(
            [event["content"] for event in events if event["type"] == "token"],
            ["Grounded ", "answer."],
        )

    def test_followup_keeps_conversation_but_resets_retrieval(self):
        agent, client, model = make_agent(
            [answer("ready_to_answer"), answer("ready_to_answer")]
        )
        config = {"configurable": {"thread_id": "followup"}}
        agent.invoke("B.Tech fees?", config=config)
        agent.invoke("And hostel?", config=config)
        previous = client.calls[1][0]["conversation"]
        self.assertEqual(previous[0]["text"], "B.Tech fees?")
        self.assertEqual(previous[1]["role"], "assistant")
        self.assertEqual(client.calls[1][0]["evidence"], [])
        self.assertEqual(client.calls[1][0]["history"], [])
        self.assertEqual(len(model.calls), 2)

    def test_threads_do_not_share_history(self):
        agent, client, _model = make_agent(
            [answer("ready_to_answer"), answer("ready_to_answer")]
        )
        agent.invoke(
            "Private question", config={"configurable": {"thread_id": "first"}}
        )
        agent.invoke("Other question", config={"configurable": {"thread_id": "second"}})
        self.assertEqual(client.calls[1][0]["conversation"], [])

    def test_forced_stop_is_transferred_as_a_limitation(self):
        agent, _client, model = make_agent([answer("read_more", "invalid")])
        agent.invoke("fees", config={"configurable": {"thread_id": "limited"}})
        context = json.loads(model.calls[0][-1].content.split("\n", 1)[1])
        self.assertEqual(context["stop_reason"], "invalid_decision")
        self.assertTrue(context["limitation"])
        self.assertEqual(context["sources"], [])


class AsyncGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_uses_same_handoff_and_streams_only_final_answer(self):
        agent, client, model = make_agent(
            [read_first, read_first, answer("ready_to_answer")],
            system_prompt="Speak briefly.",
        )
        events = [
            event
            async for event in agent.astream(
                "Hostel fees?", config={"configurable": {"thread_id": "voice"}}
            )
        ]
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(model.calls[0][0].content, "Speak briefly.")
        self.assertEqual(events[-1]["full_content"], "Grounded answer.")

    async def test_voice_cancellation_never_calls_answer_model(self):
        started, cancelled = asyncio.Event(), asyncio.Event()

        class WaitingClient:
            async def adecide(self, *_args):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        agent, _client, model = make_agent([])
        agent.retriever.client = WaitingClient()

        async def consume():
            async for _event in agent.astream(
                "fees", config={"configurable": {"thread_id": "cancel"}}
            ):
                pass

        task = asyncio.create_task(consume())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cancelled.is_set())
        self.assertEqual(model.calls, [])
