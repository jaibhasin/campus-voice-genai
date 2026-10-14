"""Direct, validated multi-path reads from the local PageIndex corpus."""

import json
from dataclasses import dataclass

from langsmith import traceable
from pydantic import BaseModel, ConfigDict, Field

from .decision_tracing import _trace_inputs


class PageIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    branch_ids: list[str] = Field(min_length=1, max_length=3)
    source_ids: list[str] = Field(min_length=1, max_length=6)


PAGEINDEX_TOOL = {
    "type": "function",
    "function": {
        "name": "read_pageindex",
        "description": (
            "Read actual college source text before stating TIET facts. Select source IDs "
            "directly from any tree depth under up to three catalog branch IDs in ONE "
            "request. Put up to three outlines in branch_ids and ALL selected sources in "
            "ONE source_ids list of at most six distinct IDs TOTAL, covering relevant "
            "conditions and exceptions. Each source must descend from a selected branch. "
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
    def read(self, selection, seen, byte_budget):
        request = PageIndexRequest.model_validate(selection)
        ids = request.source_ids
        if len(ids) != len(set(ids)):
            raise ValueError("Select at most six distinct PageIndex sources")
        if len(request.branch_ids) != len(set(request.branch_ids)):
            raise ValueError("Select distinct PageIndex branches")
        paths = {branch_id: [] for branch_id in request.branch_ids}
        for branch_id in paths:
            branch = self.store.targets.get(branch_id)
            if branch is None or branch.kind != "outline":
                raise ValueError("PageIndex branch must be a catalog outline")
        for source_id in ids:
            source = self.store.targets.get(source_id)
            branch_id = next((key for key in paths if key in self.ancestors.get(source_id, ())), None)
            if source is None or source.kind != "source" or branch_id is None or source_id in seen:
                raise ValueError("PageIndex source must be unread and belong to its branch")
            paths[branch_id].append(source_id)
        # Give each selected branch a chance before taking a second source from one.
        ordered = [
            sources[index]
            for index in range(max(len(sources) for sources in paths.values()))
            for sources in paths.values() if index < len(sources)
        ]
        evidence, omitted = [], []
        for source_id in ordered:
            source = self.store.targets[source_id].evidence()
            if len(compact_json([*evidence, source]).encode("utf-8")) > byte_budget:
                omitted.append(source_id)
                continue
            evidence.append(source)
        return BatchRead(evidence, omitted)
