"""OpenAI Decisions adapter for the bounded PageIndex retrieval controller."""

import json
import os
import threading

import httpx
from langsmith import traceable

from .decision_tracing import _trace_inputs, _trace_model, _trace_outputs


class DecisionError(RuntimeError):
    """A decision failed without exposing upstream bodies or credentials."""


class DecisionsClient:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.model = "gpt-6-luna"
        self._sync = None
        self._async = None
        self._init_lock = threading.Lock()

    def _options(self):
        key = self.api_key or os.getenv("OPENAI_API_KEY", "")
        if not key.strip():
            raise DecisionError("Missing OPENAI_API_KEY")
        return {
            "base_url": "https://api.openai.com/v1/",
            "headers": {"Authorization": f"Bearer {key}"},
            "http2": True,
        }

    def _payload(self, state, questions):
        return {
            "model": self.model,
            "input": json.dumps(state, ensure_ascii=False),
            "questions": [
                {
                    "name": name,
                    "type": "choice",
                    "instructions": question["instructions"],
                    "choices": [
                        {"value": value, "description": description}
                        for value, description in question["criteria"].items()
                    ],
                }
                for name, question in questions.items()
            ],
        }

    @staticmethod
    def _response(response, questions):
        response.raise_for_status()
        result = response.json()
        answers = result["answers"]
        if not isinstance(answers, list):
            raise ValueError("Expected named decision answers")
        named = {answer["name"]: answer for answer in answers}
        if len(named) != len(answers) or set(named) != set(questions):
            raise ValueError("Missing, duplicate, or unexpected decision answers")
        return {**result, "answers": named}

    @traceable(
        name="openai_decision",
        run_type="llm",
        process_inputs=_trace_inputs,
        process_outputs=_trace_outputs,
        tags=["openai", "retrieval"],
    )
    def decide(self, state, questions, timeout):
        _trace_model(self.model, "openai")
        with self._init_lock:
            if self._sync is None:
                self._sync = httpx.Client(**self._options())
        try:
            response = self._sync.post(
                "decisions", json=self._payload(state, questions), timeout=timeout
            )
            return self._response(response, questions)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise DecisionError("OpenAI Decisions request failed") from None

    @traceable(
        name="openai_decision",
        run_type="llm",
        process_inputs=_trace_inputs,
        process_outputs=_trace_outputs,
        tags=["openai", "retrieval"],
    )
    async def adecide(self, state, questions, timeout):
        _trace_model(self.model, "openai")
        with self._init_lock:
            if self._async is None:
                self._async = httpx.AsyncClient(**self._options())
        try:
            response = await self._async.post(
                "decisions", json=self._payload(state, questions), timeout=timeout
            )
            return self._response(response, questions)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise DecisionError("OpenAI Decisions request failed") from None

    def close(self):
        if self._sync is not None:
            self._sync.close()
            self._sync = None

    async def aclose(self):
        self.close()
        if self._async is not None:
            await self._async.aclose()
            self._async = None
