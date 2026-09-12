from __future__ import annotations

import json
from pathlib import Path
import re
import runpy
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/kb"))
PROGRAM = runpy.run_path(str(ROOT / "scripts/kb/guardian_program.py"))


class DistributedTaskContractTests(unittest.TestCase):
    def example(self):
        text = (ROOT / "spec/task-contract.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```json\n(.*?)\n```", text, re.S)
        self.assertEqual(len(blocks), 1)
        return json.loads(blocks[0])

    def test_distributed_example_passes_real_managed_task_parser(self):
        example = self.example()
        self.assertEqual(PROGRAM["_validate_task"](example), example)
        self.assertNotIn("grant", example)

    def test_malformed_scope_tier_and_missing_gate_are_rejected(self):
        mutations = (("capability_tier", "unknown"), ("owned_paths", ["../escape"]),
                     ("owned_paths", ["/absolute"]), ("evidence_gates", {}),
                     ("model", "provider-specific"))
        for key, value in mutations:
            example = self.example()
            example[key] = value
            with self.subTest(field=key, value=value), self.assertRaises(PROGRAM["GuardianProgramError"]):
                PROGRAM["_validate_task"](example)

    def test_public_authoring_references_are_present_without_formal_corpus(self):
        spec = ROOT / "spec/task-authoring.md"
        references = re.findall(r"\]\(([^)]+)\)", spec.read_text(encoding="utf-8"))
        self.assertEqual(len(references), 2)
        for relative in references:
            target = (spec.parent / relative).resolve()
            self.assertTrue(target.is_relative_to(ROOT))
            self.assertTrue(target.is_file())
            self.assertNotIn("knowledge", target.relative_to(ROOT).parts)


if __name__ == "__main__":
    unittest.main()
