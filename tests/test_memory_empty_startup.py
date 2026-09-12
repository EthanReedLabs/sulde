"""Synthetic empty-store regressions: never read a real project's memory."""
import importlib.util
from pathlib import Path
import sqlite3
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("memory_empty_startup", ROOT / "tools/kb-index/memory.py")
MEMORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MEMORY)


class EmptyMemoryStartupTests(unittest.TestCase):
    def database(self, schema=True):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        self.addCleanup(connection.close)
        if schema:
            MEMORY.create_schema(connection)
        return connection

    def test_empty_store_never_initializes_model_or_embeds(self):
        for embed in (True, False):
            with self.subTest(embed=embed):
                connection = self.database()
                before = connection.total_changes
                with mock.patch.object(MEMORY, "_model", side_effect=AssertionError("model loaded")), \
                     mock.patch.object(MEMORY, "embed_pending", side_effect=AssertionError("embedding invoked")):
                    self.assertEqual(MEMORY.search_memory(
                        "synthetic query", connection=connection, embed_pending_entries=embed), [])
                self.assertEqual(connection.total_changes, before)
                self.assertEqual(connection.execute("SELECT count(*) FROM mem_entries").fetchone()[0], 0)

    def test_owned_connection_closes_on_empty_return(self):
        connection = self.database()
        with mock.patch.object(MEMORY, "connect", return_value=connection):
            self.assertEqual(MEMORY.search_memory("synthetic query"), [])
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_missing_schema_is_not_reported_as_empty(self):
        connection = self.database(schema=False)
        with mock.patch.object(MEMORY, "_model", side_effect=AssertionError("model loaded")):
            with self.assertRaises(sqlite3.OperationalError):
                MEMORY.search_memory("synthetic query", connection=connection)

    def test_nonempty_store_retains_existing_model_requirement(self):
        connection = self.database()
        MEMORY.add_entry(connection, project="synthetic", session_id="synthetic-session",
                         role="user", content="Synthetic retained memory for regression testing.",
                         ts="2026-01-01T00:00:00Z")
        self.assertEqual(connection.execute("SELECT count(*) FROM mem_entries").fetchone()[0], 1)
        with mock.patch.object(MEMORY, "_model", side_effect=RuntimeError("synthetic model required")) as model:
            with self.assertRaisesRegex(RuntimeError, "synthetic model required"):
                MEMORY.search_memory("synthetic query", connection=connection)
            model.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
