"""One TypeSafe request returns both the action and next retrieval target."""

import json
import os
import threading

import httpx2
from langsmith import get_current_run_tree, traceable
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy, TypeSafeClient


def _trace_inputs(inputs):
    # Never serialize a client instance or its credentials into a trace.
    return {
        key: value for key, value in inputs.items() if key not in {"self", "on_fetch"}
    }


def _trace_outputs(response):
    if response is None:
        return {}
    outputs = dict(response)
    # Keep structured decisions and expose the standard LangSmith model output.
    outputs["choices"] = [
        {"message": {"role": "assistant", "content": json.dumps(response["answers"])}}
    ]
    usage = response.get("usage") or {}
    if all(
        type(usage.get(key)) is int and usage[key] >= 0
        for key in ("input_tokens", "output_tokens")
    ):
        outputs["usage_metadata"] = {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["input_tokens"] + usage["output_tokens"],
        }
    return outputs


def _trace_model(model):
    run = get_current_run_tree()
    if run is not None:
        run.metadata.update({"ls_provider": "typesafe", "ls_model_name": model})


class JevClient:
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key
        self.model = model or os.getenv("JEV_MODEL", "jev-1.13.0")
        self._sync = None
        self._async = None
        self._init_lock = threading.Lock()

    def _options(self):
        key = self.api_key or os.getenv("TYPESAFE_API_KEY", "")
        if not key.strip():
            raise RuntimeError("Missing TYPESAFE_API_KEY")
        return {
            "api_key": key,
            "model": self.model,
            # A single request per round, without hidden retry delays.
            "retry": RetryPolicy(max_retries=0),
        }

    @traceable(
        name="jev_decision",
        run_type="llm",
        process_inputs=_trace_inputs,
        process_outputs=_trace_outputs,
        tags=["jev", "retrieval"],
    )
    def decide(self, state, questions, timeout):
        _trace_model(self.model)
        with self._init_lock:
            if self._sync is None:
                self._sync = TypeSafeClient(
                    **self._options(), http_client=httpx2.Client(http2=True)
                )
        response = self._sync.system_one(state, questions, timeout=timeout)
        _trace_model(response.model or self.model)
        return response.model_dump(mode="json")

    @traceable(
        name="jev_decision",
        run_type="llm",
        process_inputs=_trace_inputs,
        process_outputs=_trace_outputs,
        tags=["jev", "retrieval"],
    )
    async def adecide(self, state, questions, timeout):
        _trace_model(self.model)
        with self._init_lock:
            if self._async is None:
                self._async = AsyncTypeSafeClient(
                    **self._options(), http_client=httpx2.AsyncClient(http2=True)
                )
        response = await self._async.system_one(state, questions, timeout=timeout)
        _trace_model(response.model or self.model)
        return response.model_dump(mode="json")

    def close(self):
        if self._sync is not None:
            self._sync.close()
            self._sync = None

    async def aclose(self):
        self.close()
        if self._async is not None:
            await self._async.aclose()
            self._async = None
