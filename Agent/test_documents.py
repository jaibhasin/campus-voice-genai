import unittest

from Agent.documents import DocumentStore, text_parts


class DocumentStoreTests(unittest.TestCase):
    def test_unicode_chunks_preserve_complete_source(self):
        text = "Fees ₹१२३ and rules. " * 1000
        parts = text_parts(text)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(part.encode("utf-8")) <= 6000 for part in parts))

    def test_summary_is_not_exposed_as_source_text(self):
        store = DocumentStore(
            {
                "fees": {
                    "tree": {"result": [{"node_id": "0000", "summary": "A fee claim"}]},
                    "pages": {
                        "result": [{"page_index": 1, "markdown": "Actual fee table"}]
                    },
                }
            }
        )
        sources = [
            target for target in store.targets.values() if target.kind == "source"
        ]
        self.assertEqual([source.text for source in sources], ["Actual fee table"])
        with self.assertRaises(ValueError):
            store.targets[store.roots[0]].evidence()

    def test_repeated_node_ids_have_distinct_source_ids(self):
        store = DocumentStore(
            {
                name: {
                    "tree": {"result": [{"node_id": "0000", "text": name}]},
                }
                for name in ["fees", "scholarships"]
            }
        )
        sources = [
            target for target in store.targets.values() if target.kind == "source"
        ]
        self.assertEqual(len({source.id for source in sources}), 2)
        self.assertEqual(
            {source.document for source in sources}, {"fees", "scholarships"}
        )

    def test_wide_outline_keeps_every_source_reachable(self):
        store = DocumentStore(
            {
                "large": {
                    "tree": {
                        "result": [
                            {"node_id": str(index), "text": f"Evidence {index}"}
                            for index in range(300)
                        ]
                    }
                }
            }
        )
        reachable = []

        def visit(target_id):
            target = store.targets[target_id]
            if target.kind == "source":
                reachable.append(target.text)
            else:
                self.assertLessEqual(len(target.children), 120)
                for child in target.children:
                    visit(child)

        for root in store.roots:
            visit(root)
        self.assertEqual(len(reachable), 300)
