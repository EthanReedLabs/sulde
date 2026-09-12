from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import sqlite3
import unittest
from unittest import mock

try:
    import numpy as np
except ModuleNotFoundError as error:  # optional dependency lives in the Sulde venv
    raise unittest.SkipTest("numpy is unavailable in the current test interpreter") from error


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sulde_memory_rerank", ROOT / "tools" / "kb-index" / "memory.py"
)
assert SPEC and SPEC.loader
memory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory)


class EmbeddingStub:
    def query_embed(self, _query: str):
        yield np.asarray([1.0, 0.0], dtype=np.float32)


class RerankerStub:
    def __init__(self, scores):
        self.scores = scores

    def rerank(self, _query: str, documents):
        assert len(list(documents)) == len(self.scores)
        return iter(self.scores)


class RerankTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        memory.create_schema(self.db)
        rows = (
            (1, "chat", "alpha lexical recent chatter", [1.0, 0.0]),
            (2, "summary", "deep root cause and durable conclusion", [0.8, 0.2]),
        )
        for entry_id, role, content, vector in rows:
            self.db.execute(
                """INSERT INTO mem_entries
                   (id, project, session_id, role, content, content_hash, ts, embedded)
                   VALUES (?, 'demo', 'session', ?, ?, ?, '2026-08-09', 1)""",
                (entry_id, role, content, str(entry_id)),
            )
            array = np.asarray(vector, dtype=np.float32)
            self.db.execute(
                "INSERT INTO mem_vectors(id, dim, vector) VALUES (?, ?, ?)",
                (entry_id, array.size, array.tobytes()),
            )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def search(self):
        with mock.patch.object(memory, "_model", return_value=EmbeddingStub()), mock.patch.object(
            memory, "segmented_query", return_value=""
        ):
            return memory.search_memory("root cause", connection=self.db, limit=2)

    def test_injected_scores_rerank_top_candidates(self) -> None:
        with mock.patch.object(
            memory, "_reranker_model", return_value=RerankerStub([0.1, 0.9])
        ), mock.patch.dict(os.environ, {"SULDE_RERANK": "on"}):
            results = self.search()

        self.assertEqual([item["id"] for item in results], [2, 1])
        self.assertGreater(results[0]["rerank_score"], results[1]["rerank_score"])
        self.assertIn("score", results[0])
        self.assertIn("cosine", results[0])

    def test_off_switch_returns_hybrid_order(self) -> None:
        with mock.patch.object(memory, "_reranker_model") as loader, mock.patch.dict(
            os.environ, {"SULDE_RERANK": "off"}
        ):
            results = self.search()

        loader.assert_not_called()
        self.assertEqual([item["id"] for item in results], [1, 2])
        self.assertNotIn("rerank_score", results[0])

    def test_missing_model_warns_once_and_falls_back(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(
            memory, "_reranker_model", side_effect=ValueError("missing")
        ), mock.patch.dict(os.environ, {"SULDE_RERANK": "on"}), mock.patch(
            "sys.stderr", stderr
        ):
            results = self.search()

        self.assertEqual([item["id"] for item in results], [1, 2])
        self.assertNotIn("rerank_score", results[0])
        self.assertEqual(len(stderr.getvalue().strip().splitlines()), 1)
        self.assertIn("using hybrid ranking", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
