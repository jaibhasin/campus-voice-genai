"""Read PageIndex exports without model calls or LangChain tool wrappers."""

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "pageindex_data"


def text_parts(text: str, max_bytes: int = 6000) -> list[str]:
    """Keep every character while bounding the size of individual sources."""
    parts, current, size = [], [], 0
    for char in text:
        width = len(char.encode("utf-8"))
        if current and size + width > max_bytes:
            parts.append("".join(current))
            current, size = [], 0
        current.append(char)
        size += width
    if current:
        parts.append("".join(current))
    return parts


@dataclass(frozen=True)
class Target:
    id: str
    kind: str
    document: str
    title: str
    summary: str = ""
    page: int | None = None
    node_id: str | None = None
    text: str = ""
    children: tuple[str, ...] = ()

    def description(self) -> dict:
        return {
            "kind": self.kind,
            "document": self.document,
            "title": self.title,
            "summary": self.summary,
            "page": self.page,
            "node_id": self.node_id,
        }

    def evidence(self) -> dict:
        if self.kind != "source" or not self.text.strip():
            raise ValueError("Navigation targets are not source evidence")
        return {"source_id": self.id, **self.description(), "text": self.text}


class DocumentStore:
    """Stable opaque target IDs keep Jev's option keys short and unambiguous."""

    def __init__(self, documents: dict):
        self.documents = documents
        self.targets: dict[str, Target] = {}
        self.roots: list[str] = []
        for name, data in sorted(documents.items()):
            sources = []

            def add_text(
                title,
                text,
                summary="",
                page=None,
                node_id=None,
                sources=sources,
                document=name,
            ):
                parts = text_parts(text)
                for index, part in enumerate(parts, 1):
                    label = (
                        f"{title} (part {index}/{len(parts)})"
                        if len(parts) > 1
                        else title
                    )
                    sources.append(
                        self._add(
                            kind="source",
                            document=document,
                            title=label,
                            summary=summary[:400],
                            page=page,
                            node_id=node_id,
                            text=part,
                        )
                    )

            def visit(nodes, ancestors=()):
                for node in nodes:
                    title = (*ancestors, node.get("title", "Untitled section"))
                    text = node.get("text") or ""
                    if text.strip():
                        add_text(
                            " / ".join(title),
                            text,
                            node.get("prefix_summary") or node.get("summary") or "",
                            node.get("page_index", node.get("start_index")),
                            node.get("node_id"),
                        )
                    visit(node.get("nodes", []), title)

            visit(data.get("tree", {}).get("result", []))
            # Offer original pages too: a node's text can omit a table or have gaps.
            for page in data.get("pages", {}).get("result", []):
                text = page.get("markdown") or ""
                if text.strip():
                    number = page.get("page_index")
                    add_text(f"Page {number}", text, text[:200], page=number)

            # Wide outlines stay reachable through explicit groups, never truncation.
            while len(sources) > 120:
                sources = [
                    self._add(
                        kind="outline",
                        document=name,
                        title=f"Sections and pages {offset + 1}-{min(offset + 120, len(sources))}",
                        children=tuple(sources[offset : offset + 120]),
                    )
                    for offset in range(0, len(sources), 120)
                ]
            metadata = data.get("metadata", {})
            self.roots.append(
                self._add(
                    kind="outline",
                    document=name,
                    title=metadata.get("name") or name,
                    summary=(metadata.get("description") or "")[:400],
                    children=tuple(sources),
                )
            )
        # Also bound the initial menu when the corpus grows beyond one Choice.
        while len(self.roots) > 120:
            roots = self.roots
            self.roots = [
                self._add(
                    kind="outline",
                    document="",
                    title=f"Documents {offset + 1}-{min(offset + 120, len(roots))}",
                    children=tuple(roots[offset : offset + 120]),
                )
                for offset in range(0, len(roots), 120)
            ]

    def _add(self, **fields) -> str:
        target_id = f"t{len(self.targets):05d}"
        self.targets[target_id] = Target(id=target_id, **fields)
        return target_id

    @classmethod
    def load(cls, directory: Path = DATA_DIR):
        documents = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        }
        return cls(documents)
