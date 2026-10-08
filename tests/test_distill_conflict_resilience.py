"""A rejected annotation sample must not stall the distillation pipeline."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


memory = module("resilience_memory", "tools/kb-index/memory.py")
annotation = module("resilience_annotation", "scripts/kb/memory_annotation.py")
distill = module("resilience_distill", "scripts/kb/auto-distill.py")


class ConflictIdentityTests(unittest.TestCase):
    """A conflict must stay distinguishable from a backend failure."""

    def test_one_protocol_constant_is_shared_by_both_sides(self):
        self.assertEqual(annotation.CONFLICT_EXIT_CODE, memory.CONFLICT_EXIT_CODE)
        self.assertEqual(annotation.CONFLICT_EXIT_CODE, distill.ANNOTATION_CONFLICT_EXIT)
        self.assertNotEqual(annotation.CONFLICT_EXIT_CODE, 2)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.database = self.home / "memory.db"
        memory.initialize(self.database)

    def annotate(self, kind):
        return {
            "entities": [{"name": "蒸馏水位", "type": kind}],
            "edges": [{"src": "蒸馏水位", "rel": "属于", "dst": "蒸馏水位",
                       "entry_id": None, "confidence": 0.9}],
            "extracted_by": "codex",
        }

    def run_cli(self, payload):
        stderr = io.StringIO()
        argv = ["memory.py", "annotate", "--json", json.dumps(payload, ensure_ascii=False)]
        # Bind both the CLI preflight and its real connection to the same DB.
        # Mocking connect alone lets an unrelated inherited home decide whether
        # the initialized fixture database is considered present.
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(self.home)}), \
             mock.patch.object(sys, "argv", argv), \
             contextlib.redirect_stderr(stderr), \
             contextlib.redirect_stdout(io.StringIO()):
            code = memory.main()
        return code, stderr.getvalue()

    def test_fixture_does_not_depend_on_an_inherited_database(self):
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(self.home / "absent")}):
            code, stderr = self.run_cli(self.annotate("组件"))
        self.assertEqual(code, 0, stderr)
        self.assertFalse((self.home / "absent").exists())

    def test_real_annotation_cli_preserves_success_and_conflict_protocol(self):
        environment = {**os.environ, "SULDE_KB_HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        def invoke(kind):
            return subprocess.run(
                [sys.executable, "-B", str(ROOT / "tools/kb-index/memory.py"), "annotate", "--json",
                 json.dumps(self.annotate(kind), ensure_ascii=False)],
                env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=False, timeout=30)
        first = invoke("组件")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)["status"], "created")
        conflict = invoke("工具")
        self.assertEqual(conflict.returncode, memory.CONFLICT_EXIT_CODE, conflict.stderr)
        self.assertEqual(json.loads(conflict.stderr)["code"], "memory_annotation_conflict")
        with contextlib.closing(memory.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT type FROM mem_entities WHERE name=?", ("蒸馏水位",)).fetchone()[0], "组件")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mem_annotation_receipts").fetchone()[0], 1)

    def test_cli_reports_a_conflict_with_its_own_exit_code_and_machine_code(self):
        first, _ = self.run_cli(self.annotate("组件"))
        self.assertEqual(first, 0)

        code, stderr = self.run_cli(self.annotate("工具"))
        self.assertEqual(code, memory.CONFLICT_EXIT_CODE)
        self.assertEqual(json.loads(stderr)["code"], "memory_annotation_conflict")

    def test_an_ordinary_validation_error_keeps_the_generic_exit_code(self):
        code, stderr = self.run_cli({"entities": [], "edges": [], "extracted_by": "nobody"})
        self.assertEqual(code, 2)
        self.assertNotIn("memory_annotation_conflict", stderr)


class RejectedSampleTests(unittest.TestCase):
    """Invariant: one unusable sample can never block the pipeline forever."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.window = distill.Window(
            entries=[distill.Entry(1, "assistant", "窗口内容")], skipped=None
        )
        self.parsed = {
            "entities": [{"name": "甲", "type": "组件"}],
            "edges": [{"src": "甲", "rel": "依赖", "dst": "乙",
                       "entry_id": 1, "confidence": 0.9}],
            "lessons": [],
        }

    @contextlib.contextmanager
    def rejecting_pipeline(self):
        with mock.patch.object(distill, "run_llm", return_value="{}"), \
             mock.patch.object(distill, "parse_result", return_value=self.parsed), \
             mock.patch.object(distill, "annotate",
                               side_effect=distill.AnnotationRejected("entity type conflicts")), \
             mock.patch.object(distill, "append_candidates") as candidates:
            yield candidates

    def test_a_rejected_sample_does_not_raise_so_the_watermark_advances(self):
        with self.rejecting_pipeline():
            counts, lessons, rejection = distill.distill_window(self.home, "cmd", self.window)
        self.assertEqual(counts, {"entities_inserted": 0, "inserted": 0})
        self.assertEqual(lessons, 0)
        self.assertIn("entity type conflicts", rejection)

    def test_lessons_survive_a_rejected_graph_annotation(self):
        with self.rejecting_pipeline() as candidates:
            distill.distill_window(self.home, "cmd", self.window)
        candidates.assert_called_once()

    def test_a_rejected_sample_is_kept_for_review(self):
        with self.rejecting_pipeline():
            distill.distill_window(self.home, "cmd", self.window)
        record = json.loads((self.home / "distill-rejected.jsonl").read_text("utf-8"))
        self.assertEqual(record["entities"], self.parsed["entities"])
        self.assertIn("entity type conflicts", record["reason"])

    def test_a_rejection_is_visible_to_the_operator(self):
        # A rejected sample reports 0 entities and 0 edges; without a reason it
        # is indistinguishable from a window that simply had nothing to extract.
        with mock.patch.object(distill, "notify") as notify:
            distill.notify_result({"entities_inserted": 0, "inserted": 0}, 0, "conflict")
        self.assertIn("被拒", notify.call_args[0][0])

        with mock.patch.object(distill, "notify") as notify:
            distill.notify_result({"entities_inserted": 0, "inserted": 0}, 0)
        self.assertNotIn("被拒", notify.call_args[0][0])

    def test_a_backend_failure_still_stalls_the_watermark(self):
        with mock.patch.object(distill, "run_llm", return_value="{}"), \
             mock.patch.object(distill, "parse_result", return_value=self.parsed), \
             mock.patch.object(distill, "annotate",
                               side_effect=distill.DistillError("backend unavailable")), \
             mock.patch.object(distill, "append_candidates"):
            with self.assertRaises(distill.DistillError):
                distill.distill_window(self.home, "cmd", self.window)


class VocabularyTests(unittest.TestCase):
    def test_the_prompt_offers_the_enum_and_forbids_inventing_types(self):
        prompt = distill.build_prompt([distill.Entry(1, "user", "内容")])
        self.assertNotIn("__ENTITY_TYPES__", prompt)
        self.assertIn("|".join(distill.ENTITY_TYPES), prompt)
        self.assertIn("不得自创", prompt)

    def test_v2_still_accepts_a_legacy_free_form_type(self):
        # Enforcing the enum inside normalize() would retroactively invalidate
        # every stored v2 receipt; that needs a schema bump, not a constant.
        value = annotation.normalize({
            "entities": [{"name": "旧实体", "type": "一个从未进入枚举的历史类型"}],
            "edges": [{"src": "旧实体", "rel": "关联", "dst": "旧实体",
                       "entry_id": None, "confidence": 0.5}],
            "extracted_by": "import",
        })
        self.assertEqual(value["entities"][0]["type"], "一个从未进入枚举的历史类型")


if __name__ == "__main__":
    unittest.main()
