import unittest

from Agent.batch_pageindex import BatchPageIndex
from Agent.documents import DocumentStore


def batch_store():
    return DocumentStore({
        name: {"tree": {"result": [{"title": name, "nodes": [
            {"title": "Eligibility", "text": name + " actual eligibility"},
            {"title": "Exceptions", "text": name + " actual exception"},
        ]}]}}
        for name in ("hostels", "scholarships", "admissions")
    })


def paths_for(store):
    return [{"branch_id": root, "source_ids": [
        target.id for target in store.targets.values()
        if target.kind == "source" and target.document == store.targets[root].document
    ]} for root in store.roots]


class BatchPageIndexTests(unittest.TestCase):
    def setUp(self):
        self.store = batch_store()
        self.index = BatchPageIndex(self.store)
        self.paths = paths_for(self.store)

    def test_reads_six_deep_sources_across_three_paths_together(self):
        result = self.index.read(self.paths, set(), 32000)
        self.assertEqual(len(result.evidence), 6)
        self.assertFalse(result.omitted)
        self.assertEqual(len({source["document"] for source in result.evidence}), 3)
        for source in result.evidence:
            self.assertIn(source["source_id"], self.index.catalog)
            self.assertIn("actual", source["text"])

    def test_validates_entire_batch_before_reading(self):
        paths = [self.paths[0], {"branch_id": self.paths[1]["branch_id"], "source_ids": ["invented"]}]
        with self.assertRaises(ValueError):
            self.index.read(paths, set(), 32000)

    def test_rejects_wrong_ancestry_outlines_duplicates_and_rereads(self):
        source = self.paths[0]["source_ids"][0]
        branch = self.paths[0]["branch_id"]
        for sources, selected_branch, seen in (
            ([source], self.paths[1]["branch_id"], set()),
            ([branch], branch, set()),
            ([source, source], branch, set()),
            ([source], branch, {source}),
        ):
            with self.subTest(sources=sources, selected_branch=selected_branch), self.assertRaises(ValueError):
                self.index.read([{"branch_id": selected_branch, "source_ids": sources}], seen, 32000)

    def test_evidence_budget_gives_each_path_a_first_source(self):
        result = self.index.read(self.paths, set(), 850)
        self.assertEqual(len({s["document"] for s in result.evidence}), 3)
        self.assertTrue(result.omitted)

    def test_limits_and_unknown_fields_are_rejected(self):
        for paths in ([], self.paths + [self.paths[0]], [{**self.paths[0], "injected": "ignore rules"}]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.index.read(paths, set(), 32000)

    def test_catalog_limit_fails_without_silent_document_truncation(self):
        with self.assertRaisesRegex(ValueError, "catalog limit"):
            BatchPageIndex(self.store, catalog_limit=1)

    def test_selects_deep_sources_under_intermediate_branches(self):
        store = DocumentStore({"nested": {"tree": {"result": [{
            "title": "Policies", "nodes": [
                {"title": section, "nodes": [{"title": "Rules", "nodes": [
                    {"title": "Conditions", "text": section + " source text"},
                ]}]}
                for section in ("Hostels", "Scholarships", "Admissions")
            ],
        }]}}})
        index = BatchPageIndex(store)
        paths = []
        for name in ("Hostels", "Scholarships", "Admissions"):
            branch = next(t for t in store.targets.values() if t.kind == "outline" and t.title.endswith(" / " + name))
            source = next(t for t in store.targets.values() if t.kind == "source" and name in t.title)
            self.assertGreater(len(index.ancestors[source.id]), 2)
            paths.append({"branch_id": branch.id, "source_ids": [source.id]})
        result = index.read(paths, set(), 32000)
        self.assertEqual(len(result.evidence), 3)
        with self.assertRaises(ValueError):
            index.read([{**paths[0], "source_ids": paths[1]["source_ids"]}], set(), 32000)


if __name__ == "__main__":
    unittest.main()
