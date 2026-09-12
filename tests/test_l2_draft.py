from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kb" / "l2-draft.py"
SPEC = importlib.util.spec_from_file_location("l2_draft", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
L2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(L2)


class L2DraftRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def seed_all_channels(self) -> None:
        (self.home / "self-repair").mkdir()
        (self.home / "self-repair" / "pending.json").write_text(
            json.dumps([{"slug": "wp-one", "status": "pending", "brief_path": "/tmp/wp.md"}]),
            encoding="utf-8",
        )
        (self.home / "golden-candidates.jsonl").write_text(
            json.dumps({"id": "gm-one", "query": "q"}) + "\n", encoding="utf-8"
        )
        (self.home / "distill-candidates.md").write_text(
            "- 待处理教训\n- 已处理教训（✅ 已沉淀 ap-1）\n- 存疑教训（❓ 存疑留人工）\n",
            encoding="utf-8",
        )
        governance = self.home / "governance"
        governance.mkdir()
        (governance / "report-20260811.md").write_text(
            "## 红队质疑\n\n**待审提案 P-30（不实施）**：新增覆盖率门禁。\n",
            encoding="utf-8",
        )

    def test_four_channels_form_ready_registry(self) -> None:
        self.seed_all_channels()
        result = L2.build_registry(self.home)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["missing_channels"], [])
        self.assertEqual(result["channels"]["wp_brief"]["count"], 1)
        self.assertEqual(result["channels"]["golden_case"]["count"], 1)
        self.assertEqual(result["channels"]["sediment_draft"]["pending"], 2)
        self.assertEqual(result["channels"]["threshold_proposal"]["items"][0]["id"], "P-30")

    def test_missing_channel_is_degraded_not_false_ready(self) -> None:
        (self.home / "self-repair").mkdir()
        (self.home / "self-repair" / "pending.json").write_text("[]", encoding="utf-8")
        result = L2.build_registry(self.home)
        self.assertEqual(result["status"], "degraded")
        self.assertIn("golden_case", result["missing_channels"])

    def test_atomic_registry_is_valid_json(self) -> None:
        self.seed_all_channels()
        path = self.home / "l2" / "registry.json"
        L2.atomic_json(path, L2.build_registry(self.home))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema"], "sulde-l2-registry-v1")

    def test_terminal_decision_survives_refresh_and_line_moves(self) -> None:
        self.seed_all_channels()
        first = L2.build_registry(self.home)
        item_id = first["channels"]["sediment_draft"]["items"][0]["id"]
        L2.atomic_json(self.home / "l2/registry.json", first)
        L2.transition(self.home, "sediment_draft", item_id, "rejected", "duplicate", "human")
        (self.home / "distill-candidates.md").write_text(
            "\n- 待处理教训\n- 已处理教训（✅ 已沉淀 ap-1）\n", encoding="utf-8"
        )
        refreshed = L2.build_registry(self.home)
        item = next(row for row in refreshed["channels"]["sediment_draft"]["items"] if row["id"] == item_id)
        self.assertEqual(item["status"], "rejected")
        self.assertEqual(item["actor"], "human")


if __name__ == "__main__":
    unittest.main()
