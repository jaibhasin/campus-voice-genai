import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from Agent.decisions import DecisionError, DecisionsClient
from Agent.retrieval import ACTION_QUESTION
from Agent.test_tracing import capture_traces


QUESTIONS = {
    "action": ACTION_QUESTION,
    "next_read": {
        "type": "choice",
        "instructions": "Choose the most useful source, independently of action.",
        "criteria": {"fees": "Tuition and hostel fees.", "awards": "Scholarships."},
    },
}


def response_body():
    return {
        "model": "gpt-6-luna",
        "answers": [
            {"type": "choice", "name": "action", "choice": "read_more",
             "confidence": 0.9, "probabilities": []},
            {"type": "choice", "name": "next_read", "choice": "fees",
             "confidence": 0.9, "probabilities": []},
        ],
        "usage": {"input_tokens": 100, "output_tokens": 0},
    }


class DecisionsTests(unittest.TestCase):
    def test_real_http_contract_maps_shared_multilingual_state_and_named_answers(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json=response_body())

        client = DecisionsClient(api_key="credential-must-not-appear")
        client._sync = httpx.Client(
            **client._options(), transport=httpx.MockTransport(respond)
        )
        state = {"question": "ਹੋਸਟਲ ਦੀ ਫੀਸ?", "evidence": []}
        try:
            with capture_traces() as spans:
                result = client.decide(state, QUESTIONS, 2)
            self.assertEqual(len(requests), 1)
            self.assertEqual(str(requests[0].url), "https://api.openai.com/v1/decisions")
            payload = json.loads(requests[0].content)
            self.assertEqual(payload["model"], "gpt-6-luna")
            self.assertEqual(json.loads(payload["input"]), state)
            self.assertEqual([q["name"] for q in payload["questions"]], list(QUESTIONS))
            self.assertEqual(payload["questions"][1]["choices"][0], {
                "value": "fees", "description": "Tuition and hostel fees.",
            })
            self.assertEqual(result["answers"]["next_read"]["choice"], "fees")
            span = next(s for s in spans.values() if s["name"] == "openai_decision")
            self.assertEqual(span["extra"]["metadata"]["ls_provider"], "openai")
            self.assertEqual(span["outputs"]["usage_metadata"]["output_tokens"], 0)
            self.assertNotIn(client.api_key, json.dumps(spans, default=str))
        finally:
            client.close()

    def test_http_failure_is_sanitized_and_not_retried(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(429, json={"error": "sensitive upstream body"})

        client = DecisionsClient(api_key="test-key")
        client._sync = httpx.Client(
            **client._options(), transport=httpx.MockTransport(respond)
        )
        try:
            with self.assertRaisesRegex(DecisionError, "^OpenAI Decisions request failed$"):
                client.decide({}, QUESTIONS, 1)
            self.assertEqual(len(requests), 1)
        finally:
            client.close()

    def test_missing_key_does_not_use_openrouter_credentials(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "", "OPENROUTER_API_KEY": "other"}):
            with self.assertRaisesRegex(DecisionError, "Missing OPENAI_API_KEY"):
                DecisionsClient().decide({}, QUESTIONS, 1)

    def test_malformed_answers_are_rejected_and_refusals_are_preserved(self):
        for answers in ([], response_body()["answers"] * 2, {}, [None]):
            with self.subTest(answers=answers), self.assertRaises((KeyError, TypeError, ValueError)):
                DecisionsClient._response(httpx.Response(
                    200, json={"answers": answers}, request=httpx.Request("POST", "https://example.test")
                ), QUESTIONS)
        body = response_body()
        body["answers"][0] = {"name": "action", "type": "refusal"}
        result = DecisionsClient._response(httpx.Response(
            200, json=body, request=httpx.Request("POST", "https://example.test")
        ), QUESTIONS)
        self.assertEqual(result["answers"]["action"]["type"], "refusal")


class AsyncDecisionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_request_and_cleanup(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json=response_body())

        client = DecisionsClient(api_key="test-key")
        transport = httpx.AsyncClient(
            **client._options(), transport=httpx.MockTransport(respond)
        )
        client._async = transport
        result = await client.adecide({}, QUESTIONS, 1)
        self.assertEqual(result["answers"]["action"]["choice"], "read_more")
        self.assertEqual(len(requests), 1)
        await client.aclose()
        self.assertTrue(transport.is_closed)
        self.assertIsNone(client._async)

    async def test_cancellation_propagates(self):
        started = asyncio.Event()

        async def respond(request):
            started.set()
            await asyncio.Event().wait()

        client = DecisionsClient(api_key="test-key")
        client._async = httpx.AsyncClient(
            **client._options(), transport=httpx.MockTransport(respond)
        )
        task = asyncio.create_task(client.adecide({}, QUESTIONS, 1))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await client.aclose()
