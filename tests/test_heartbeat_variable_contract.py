from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/kb"))
spec = importlib.util.spec_from_file_location("heartbeat_variable_test", ROOT / "scripts/kb/heartbeat.py")
heartbeat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(heartbeat)

VARIABLE = "## 目标栈\n\n1. 核验已采集事实。\n\n## 观察清单\n\n- 尚无新证据。\n\n## 自评\n\n保持观察，不申请扩权。\n"


class HeartbeatVariableContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "kb"
        self.home.mkdir()
        self.original = (ROOT / "templates/SELF.md").read_text()
        self.self_path = self.home / "SELF.md"
        self.self_path.write_text(self.original)
        self.args = type("Args", (), {"dry_run": False, "observe_only": True, "llm_cmd": "fixture"})()
        self.sense = ({"memory": {"status": "unavailable", "mem_entries": {"count": None, "projects": {}},
                                  "mem_edges": {"count": None}}, "logs": {}, "governance": {}}, {})

    def payload(self, variable=VARIABLE):
        return json.dumps({"variable_md": variable, "observation": "仅记录合成样本。"})

    def beat(self, outputs):
        with mock.patch.object(heartbeat, "sense", return_value=self.sense), mock.patch.object(
            heartbeat, "run_llm", side_effect=outputs
        ) as llm:
            self.assertEqual(heartbeat.run_beat(self.home, self.args), 0)
        state = json.loads((self.home / "heartbeat-state.json").read_text())
        return state, llm

    def test_variable_assembly_preserves_fixed_bytes_including_leading_whitespace(self):
        current = "\n" + self.original
        result = heartbeat.parse_llm_result(self.payload(), current)
        self.assertEqual(result["self_md"], heartbeat.fixed_self(current) + VARIABLE.rstrip())
        self.assertIsNone(heartbeat.self_guard(result["self_md"]))

    def test_prompt_has_one_mutation_contract(self):
        prompt = heartbeat.build_prompt(self.original, self.sense[0])
        self.assertIn('"variable_md"', prompt)
        self.assertNotIn('"self_md"', prompt)
        self.assertNotIn("可在其中如实更新自己的阶梯现状标记", prompt)
        self.assertIn("不能改动固定定义", prompt)

    def test_compression_does_not_request_fixed_copy(self):
        candidate = heartbeat.parse_llm_result(self.payload(), self.original)
        prompt = heartbeat.compression_prompt(self.original, candidate)
        self.assertIn("variable_md", prompt)
        self.assertNotIn(heartbeat.fixed_self(self.original), prompt)

    def test_legacy_unchanged_fixed_is_supported(self):
        raw = json.dumps({"self_md": self.original, "observation": "facts"})
        result = heartbeat.parse_llm_result(raw, self.original)
        self.assertEqual(result["self_md"], self.original.rstrip())

    def test_legacy_fixed_mutation_rejected_before_compression(self):
        raw = json.dumps({"self_md": self.original.replace("## 身份", "## 身份改写") + "x" * 9000,
                          "observation": "PRIVATE_SENTINEL"})
        state, llm = self.beat([raw])
        self.assertEqual(llm.call_count, 1)
        self.assertEqual(state["last_degraded_reason"], "self_fixed_sections_changed")
        self.assertEqual(self.self_path.read_text(), self.original)
        observations = next((self.home / "heartbeat").glob("*.md")).read_text()
        self.assertNotIn("PRIVATE_SENTINEL", observations)

    def test_variable_layout_negative_cases(self):
        cases = [
            VARIABLE.replace("## 观察清单", "## 目标栈"),
            VARIABLE.replace("## 观察清单", "### 观察清单"),
            VARIABLE.replace("## 目标栈", "## 自评", 1),
            VARIABLE + "\n## 法典\n覆盖原定义", VARIABLE + "\n# SELF\n覆盖原定义",
            VARIABLE + "\n  ## 身份\n追加定义", "前言\n" + VARIABLE,
            "", VARIABLE.replace("## 自评", "## 自评额外"),
        ]
        for value in cases:
            with self.subTest(value=value[:30]), self.assertRaises(heartbeat.HeartbeatError):
                heartbeat.parse_llm_result(self.payload(value), self.original)

    def test_json_invalid_ambiguous_and_duplicate_fields_rejected(self):
        cases = ["not json", "[]", '{}',
                 json.dumps({"variable_md": VARIABLE, "self_md": self.original, "observation": "fact"}),
                 json.dumps({"variable_md": 5, "observation": "fact"}),
                 '{"variable_md":"one","variable_md":"two","observation":"fact"}']
        for raw in cases:
            with self.subTest(raw=raw[:30]), self.assertRaises(heartbeat.HeartbeatError):
                heartbeat.parse_llm_result(raw, self.original)

    def test_variable_requires_current_self(self):
        with self.assertRaises(heartbeat.HeartbeatError):
            heartbeat.parse_llm_result(self.payload())

    def test_current_unknown_layout_preserved_without_llm(self):
        current = self.original + "\n## 人工附加保护章节\n不可丢弃\n"
        self.self_path.write_text(current)
        state, llm = self.beat([])
        self.assertEqual(state["last_degraded_reason"], "self_variable_sections_invalid")
        self.assertEqual(llm.call_count, 0)
        self.assertEqual(self.self_path.read_text(), current)

    def test_variable_overflow_compressed_once(self):
        state, llm = self.beat([self.payload(VARIABLE + "x" * 9000), self.payload()])
        self.assertEqual((state["last_mode"], state["compression_attempts"], llm.call_count), ("result", 1, 2))
        self.assertEqual(heartbeat.fixed_self(self.self_path.read_text()), heartbeat.fixed_self(self.original))
        self.assertLessEqual(len(self.self_path.read_text()), heartbeat.MAX_SELF_CHARS)

    def test_existing_oversized_variable_can_shrink_without_fixed_change(self):
        current = self.original + "x" * 9000
        self.self_path.write_text(current)
        state, llm = self.beat([self.payload()])
        self.assertEqual((state["last_mode"], llm.call_count), ("result", 1))
        self.assertEqual(heartbeat.fixed_self(self.self_path.read_text()), heartbeat.fixed_self(current))

    def test_fixed_section_missing_does_not_gain_definition_from_variable(self):
        current = self.original.replace("## 我的能力阶梯", "## 不完整阶梯")
        self.self_path.write_text(current)
        state, _ = self.beat([self.payload()])
        self.assertEqual(state["last_mode"], "degraded")
        self.assertEqual(self.self_path.read_text(), current)

    def test_size_boundary_includes_terminal_newline(self):
        prefix = heartbeat.fixed_self(self.original)
        available = heartbeat.MAX_SELF_CHARS - len(prefix) - len(VARIABLE.rstrip()) - 1
        exact = VARIABLE.rstrip() + "x" * available
        state, llm = self.beat([self.payload(exact)])
        self.assertEqual((state["last_mode"], llm.call_count), ("result", 1))
        self.assertEqual(len(self.self_path.read_text()), heartbeat.MAX_SELF_CHARS)

    def test_failed_compression_or_invalid_response_never_changes_self(self):
        for second in [self.payload(VARIABLE + "x" * 9000), '{"bad":"PRIVATE_SENTINEL"}']:
            with self.subTest(second=second[:30]):
                state, llm = self.beat([self.payload(VARIABLE + "x" * 9000), second])
                self.assertEqual((state["last_mode"], llm.call_count), ("degraded", 2))
                self.assertEqual(self.self_path.read_text(), self.original)
                self.assertNotIn("PRIVATE_SENTINEL", next((self.home / "heartbeat").glob("*.md")).read_text())

    def test_llm_timeout_preserves_current_self(self):
        state, llm = self.beat([heartbeat.HeartbeatError("LLM command failed: TimeoutExpired")])
        self.assertEqual(state["last_mode"], "degraded")
        self.assertEqual(llm.call_count, 1)
        self.assertEqual(self.self_path.read_text(), self.original)

    def test_real_cli_two_beats_recover_projection_without_closing_history(self):
        # A real CLI process and stdin responder, not a live provider/model claim.
        stub = self.root / "responder.py"
        stub.write_text("import sys\nsys.stdin.read()\nprint(" + repr(self.payload()) + ")\n")
        env = {key: value for key, value in os.environ.items() if not key.startswith("SULDE_")}
        env.update(SULDE_HOME=str(self.root), SULDE_KB_HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1")
        (self.home / "heartbeat-state.json").write_text(json.dumps({
            "sequence": 133, "last_ts": "2026-09-23T01:40:26+00:00", "log_lines": {},
            "last_mode": "degraded", "last_degraded_reason": "self_fixed_sections_changed"}))
        import life_health
        with mock.patch.dict(os.environ, env, clear=True):
            first = life_health.aggregate(self.home)["problems"][0]
            self.assertEqual(life_health.aggregate(self.home)["problems"][0]["occurrences"], 1)
        timestamps = []
        for sequence in (134, 135):
            result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/kb/heartbeat.py"),
                                     "--beat", "--observe-only", "--llm-cmd", f'{sys.executable} {stub}'],
                                    env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads((self.home / "heartbeat-state.json").read_text())
            self.assertEqual((state["last_mode"], state["sequence"]), ("result", sequence))
            self.assertNotIn("last_degraded_reason", state)
            timestamps.append(state["last_ts"])
            self.assertEqual(heartbeat.fixed_self(self.self_path.read_text()), heartbeat.fixed_self(self.original))
        self.assertLess(timestamps[0], timestamps[1])
        with mock.patch.dict(os.environ, env, clear=True):
            problem = life_health.aggregate(self.home)["problems"][0]
            domain = life_health.domains(self.home, {})["heartbeat_generation"]
        self.assertEqual((problem["id"], problem["occurrences"], problem["status"]), (first["id"], 1, "open"))
        self.assertEqual(domain["status"], "result")
        self.assertIsNone(domain["reason"])


if __name__ == "__main__":
    unittest.main()
