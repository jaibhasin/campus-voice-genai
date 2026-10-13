"""Direct, validated multi-path reads from the local PageIndex corpus."""

import json
from dataclasses import dataclass

from langsmith import traceable
from pydantic import BaseModel, ConfigDict, Field

from .decision_tracing import _trace_inputs


class SourcePath(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    branch_id: str
    source_ids: list[str] = Field(min_length=1, max_length=6)


class PageIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    paths: list[SourcePath] = Field(min_length=1, max_length=3)


PAGEINDEX_TOOL = {
    "type": "function",
    "function": {
        "name": "read_pageindex",
        "description": (
            "Read actual college source text before stating TIET facts. Select source IDs "
            "directly from any tree depth under up to three catalog branch IDs in ONE "
            "request. Each branch must be an outline ancestor of its sources. Select at "
            "most six distinct sources total, covering relevant conditions and exceptions. "
            "You may select several sources per branch. Catalog titles and summaries are "
            "navigation hints, not factual evidence. Do not fetch already-read sources."
        ),
        "parameters": PageIndexRequest.model_json_schema(),
    },
}


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class BatchRead:
    evidence: list[dict]
    omitted: list[str]


class BatchPageIndex:
    def __init__(self, store, catalog_limit=96000):
        self.store = store
        self.ancestors = {}

        def visit(target_id, parents):
            target = store.targets[target_id]
            self.ancestors[target_id] = frozenset(parents)
            entry = {"id": target_id, "title": target.title.rsplit(" / ", 1)[-1]}
            if target.kind == "outline":
                if target.summary:
                    entry["summary"] = " ".join(target.summary.split())[:120]
                entry["children"] = [visit(child, (*parents, target_id)) for child in target.children]
            else:
                if target.page is not None:
                    entry["page"] = target.page
                # Original pages lack semantic titles, so a short hint aids selection.
                if target.title.startswith("Page "):
                    entry["hint"] = " ".join(target.summary.split())[:100]
            return entry

        catalog = [visit(root, ()) for root in store.roots]
        self.catalog = compact_json(catalog)
        self.catalog_bytes = len(self.catalog.encode("utf-8"))
        if self.catalog_bytes > catalog_limit:
            raise ValueError("PageIndex catalog exceeds the normal LLM catalog limit")

    @traceable(name="read_pageindex", run_type="tool", process_inputs=_trace_inputs)
    def read(self, paths, seen, byte_budget):
        request = PageIndexRequest.model_validate({"paths": paths})
        ids = [source for path in request.paths for source in path.source_ids]
        if len(ids) > 6 or len(ids) != len(set(ids)):
            raise ValueError("Select at most six distinct PageIndex sources")
        for path in request.paths:
            branch = self.store.targets.get(path.branch_id)
            if branch is None or branch.kind != "outline":
                raise ValueError("PageIndex branch must be a catalog outline")
            for source_id in path.source_ids:
                source = self.store.targets.get(source_id)
                if (
                    source is None or source.kind != "source"
                    or path.branch_id not in self.ancestors[source_id]
                    or source_id in seen
                ):
                    raise ValueError("PageIndex source must be unread and belong to its branch")
        # Give each selected branch a chance before taking a second source from one.
        ordered = [
            path.source_ids[index]
            for index in range(max(len(path.source_ids) for path in request.paths))
            for path in request.paths if index < len(path.source_ids)
        ]
        evidence, omitted = [], []
        for source_id in ordered:
            source = self.store.targets[source_id].evidence()
            if len(compact_json([*evidence, source]).encode("utf-8")) > byte_budget:
                omitted.append(source_id)
                continue
            evidence.append(source)
        return BatchRead(evidence, omitted)
