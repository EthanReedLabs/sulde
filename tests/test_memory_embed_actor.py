from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MEMORY = ROOT / "tools" / "kb-index" / "memory.py"
WORKER = ROOT / "scripts" / "kb" / "memory-embed-worker.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class MemoryEmbedActorTests(unittest.TestCase):
    def test_persistent_runtime_reuses_one_embedding_model(self) -> None:
        memory = load("test_memory_model_cache", MEMORY)
        constructor = mock.Mock(return_value=object())
        fake_fastembed = types.SimpleNamespace(TextEmbedding=constructor)
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"SULDE_KB_HOME": temp_dir},
        ), mock.patch.dict(sys.modules, {"fastembed": fake_fastembed}):
            first = memory._model()
            second = memory._model()
        self.assertIs(first, second)
        constructor.assert_called_once()

    @unittest.skipIf(os.name == "nt", "POSIX nonblocking flock fixture")
    def test_embedding_actor_lock_admits_only_one_writer_and_recovers(self) -> None:
        memory = load("test_memory_embed_actor_memory", MEMORY)
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"SULDE_KB_HOME": temp_dir},
        ):
            with memory.embedding_actor_lock() as first:
                with memory.embedding_actor_lock() as second:
                    self.assertTrue(first)
                    self.assertFalse(second)
            with memory.embedding_actor_lock() as recovered:
                self.assertTrue(recovered)

    def test_worker_uses_neutral_venv_and_bounded_batch(self) -> None:
        worker = load("test_memory_embed_worker", WORKER)
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            launcher = home / "bin" / "kb-index"
            launcher.parent.mkdir(parents=True)
            launcher.touch()
            with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}), mock.patch.object(
                worker.subprocess,
                "run",
                return_value=mock.Mock(returncode=0),
            ) as run:
                self.assertEqual(worker.main(), 0)
            command = run.call_args.args[0]
            self.assertEqual(Path(command[0]).resolve(), launcher.resolve())
            self.assertEqual(command[-3:], ["mem-embed", "--limit", "250"])
            self.assertEqual(run.call_args.kwargs["env"]["SULDE_KB_HOME"], str(home))
            self.assertEqual(run.call_args.kwargs["timeout"], 180)


if __name__ == "__main__":
    unittest.main()
