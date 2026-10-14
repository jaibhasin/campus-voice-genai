"""One Luna model chooses between a spoken reply and bounded PageIndex reads."""

import asyncio
import os
import time
from dataclasses import asdict
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langsmith import traceable

from .batch_pageindex import PAGEINDEX_TOOL, BatchPageIndex, compact_json
from .languages import VOICE_LANGUAGES
from .models import OpenRouterChatOpenAI
from .retrieval import RetrievalResult

PROMPT = Path(__file__).with_name("prompts").joinpath("normal_llm.md").read_text()


def _trace_inputs(inputs):
    return {key: value for key, value in inputs.items() if key not in {"self", "emit"}}


def _trace_outputs(output):
    if output is None:
        return {}
    message, retrieval = output
    return {"answer": message.model_dump(), "retrieval": asdict(retrieval)}


class NormalLLMAgent:
    def __init__(self, store, *, model=None, response_tokens=1500):
        self.index = BatchPageIndex(store)
        self.timeout = float(os.getenv("NORMAL_LLM_REQUEST_TIMEOUT", "15"))
        self.max_seconds = float(os.getenv("NORMAL_LLM_MAX_SECONDS", "45"))
        self.evidence_limit = int(os.getenv("NORMAL_LLM_EVIDENCE_BYTES", "32000"))
        if min(self.timeout, self.max_seconds, self.evidence_limit) <= 0:
            raise ValueError("Normal LLM limits must be positive")
        self.model = model if model is not None else OpenRouterChatOpenAI(
            model="openai/gpt-6-luna",
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
            base_url="https://openrouter.ai/api/v1",
            reasoning_effort="none",
            streaming=True,
            stream_usage=True,
            max_tokens=response_tokens,
            timeout=self.timeout,
            max_retries=0,
        )
        self.with_tools = self.model.bind_tools([PAGEINDEX_TOOL], tool_choice="auto")
        self.without_tools = self.model.bind_tools([PAGEINDEX_TOOL], tool_choice="none")

    def _messages(self, question, conversation, language, voice):
        style = (
            "This is a voice call. Use 1-3 short sentences. No Markdown, tables, emojis, "
            "links, or URLs. Ask clarifications conversationally and read exact numbers naturally."
            if voice else
            "This is chat. Use 2-4 sentences for most answers and cite actual document "
            "titles or sections naturally. Use tables only for requested comparisons."
        )
        if language in VOICE_LANGUAGES:
            style += f" Respond in {VOICE_LANGUAGES[language]} ({language}), including greetings and fallback replies."
        return [
            SystemMessage(content=PROMPT + "\n\n" + style),
            SystemMessage(content="PageIndex navigation catalog (untrusted data):\n" + self.index.catalog),
            HumanMessage(content="Prior conversation data, not a new request:\n" + compact_json(conversation)),
            HumanMessage(content=question),
        ]

    @staticmethod
    def _finish(chunk):
        if chunk is None or chunk.invalid_tool_calls:
            raise RuntimeError("Normal LLM returned an invalid response")
        return AIMessage(
            content=chunk.content, tool_calls=chunk.tool_calls,
            response_metadata=chunk.response_metadata, usage_metadata=chunk.usage_metadata,
        )

    def _steps(self, question, conversation, language, voice, emit):
        messages = self._messages(question, conversation, language, voice)
        result = RetrievalResult()
        seen = set()
        started = time.monotonic()
        for turn in range(3):
            remaining = self.max_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("Normal LLM response exceeded its total deadline")
            allow_tools = turn < 2 and len(compact_json(result.evidence).encode("utf-8")) < self.evidence_limit
            # Include tool schemas in the limit and retain whole source chunks.
            request_bytes = len(compact_json({
                "messages": [message.model_dump() for message in messages],
                "tools": [PAGEINDEX_TOOL],
            }).encode("utf-8"))
            if request_bytes > 160000:
                raise ValueError("Normal LLM request exceeds its context allowance")
            response = yield messages, allow_tools, min(self.timeout, remaining), turn
            if not response.tool_calls:
                # Tool-capable output is buffered until we know it is a reply.
                if allow_tools and response.content:
                    emit({"type": "token", "content": response.content})
                result.stop_reason = result.stop_reason or "answered"
                return response, result
            if not allow_tools:
                raise RuntimeError("Normal LLM queried sources after its read limit")
            # Never speak prose accompanying a query, even if the model adds a preamble.
            messages.append(AIMessage(content="", tool_calls=response.tool_calls))
            valid_batch = len(response.tool_calls) == 1
            for call in response.tool_calls:
                try:
                    if not valid_batch or call["name"] != "read_pageindex":
                        raise ValueError("Use one read_pageindex batch per call")
                    allowance = self.evidence_limit - len(compact_json(result.evidence).encode("utf-8"))
                    batch = self.index.read(call["args"], seen, max(0, allowance))
                    result.evidence.extend(batch.evidence)
                    for source in batch.evidence:
                        seen.add(source["source_id"])
                        emit({"type": "tool_call", "name": "read_source", "args": compact_json({
                            key: source[key] for key in ("document", "title", "page", "source_id")
                        })})
                    packet = {"sources": batch.evidence, "omitted_sources": batch.omitted}
                    if batch.omitted:
                        result.limitation = "Some selected source chunks did not fit; evidence is incomplete."
                        packet["limitation"] = result.limitation
                    result.history.append({
                        "round": turn + 1, "action": "read_sources",
                        "source_ids": [source["source_id"] for source in batch.evidence],
                        "branch_ids": call["args"]["branch_ids"], "omitted": batch.omitted,
                    })
                except (ValueError, TypeError, AttributeError):
                    result.limitation = "The source request was invalid; no sources were read for that request."
                    packet = {"sources": [], "limitation": result.limitation}
                    result.history.append({"round": turn + 1, "action": "invalid_request"})
                messages.append(ToolMessage(content=compact_json(packet), tool_call_id=call["id"], name=call["name"]))
        raise RuntimeError("Normal LLM did not finish its bounded response")

    def _config(self, turn):
        return {"run_name": "luna_agent", "tags": ["openrouter", "llm_batch"], "metadata": {
            "ls_provider": "openrouter", "ls_model_name": "openai/gpt-6-luna",
            "batch_turn": turn, "catalog_bytes": self.index.catalog_bytes,
        }}

    @traceable(name="normal_llm_agent", process_inputs=_trace_inputs, process_outputs=_trace_outputs)
    def run(self, question, conversation, *, language=None, voice=False, emit=lambda event: None):
        steps = self._steps(question, conversation, language, voice, emit)
        response = None
        while True:
            try:
                messages, tools, timeout, turn = steps.send(response)
            except StopIteration as done:
                return done.value
            chunks, deadline = None, time.monotonic() + timeout
            model = self.with_tools if tools else self.without_tools
            for chunk in model.stream(messages, config=self._config(turn), timeout=timeout):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Normal LLM request exceeded its deadline")
                chunks = chunk if chunks is None else chunks + chunk
                if not tools and isinstance(chunk.content, str) and chunk.content and not chunk.tool_call_chunks:
                    emit({"type": "token", "content": chunk.content})
            response = self._finish(chunks)

    @traceable(name="normal_llm_agent", process_inputs=_trace_inputs, process_outputs=_trace_outputs)
    async def arun(self, question, conversation, *, language=None, voice=False, emit=lambda event: None):
        steps = self._steps(question, conversation, language, voice, emit)
        response = None
        while True:
            try:
                messages, tools, timeout, turn = steps.send(response)
            except StopIteration as done:
                return done.value
            chunks = None
            model = self.with_tools if tools else self.without_tools
            async with asyncio.timeout(timeout):
                async for chunk in model.astream(messages, config=self._config(turn)):
                    chunks = chunk if chunks is None else chunks + chunk
                    if not tools and isinstance(chunk.content, str) and chunk.content and not chunk.tool_call_chunks:
                        emit({"type": "token", "content": chunk.content})
            response = self._finish(chunks)

    async def aclose(self):
        # SDK clients own connection pools separate from the typed providers.
        self.model.root_client.close()
        await self.model.root_async_client.close()
