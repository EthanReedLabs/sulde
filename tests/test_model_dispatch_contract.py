from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ModelDispatchContractTests(unittest.TestCase):
    NEW_TASK_CONTRACT_FILES = (
        "skills/coordinator/writing-task-md/SKILL.md",
        "skills/dispatch-task/SKILL.md",
        "skills/dev/assign/SKILL.md",
        "spec/task-authoring.md",
        "spec/task-contract.md",
        "template/_project/docs-hub/00_shared-rules/task-brief.md.template",
        "template/_project/docs-hub/00_shared-rules/model-strategy.md.template",
    )

    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_new_task_contract_uses_capability_tier(self) -> None:
        for relative in self.NEW_TASK_CONTRACT_FILES:
            with self.subTest(relative=relative):
                self.assertIn("capability_tier", self.read(relative))

    def test_schema_and_short_template_do_not_define_provider_model_fields(self) -> None:
        schema = self.read("spec/task-contract.md")
        template = self.read("template/_project/docs-hub/00_shared-rules/task-brief.md.template")
        for relative, source in (("schema", schema), ("template", template)):
            with self.subTest(relative=relative):
                self.assertIsNone(
                    re.search(r"(?m)^\s*-?\s*model:\s*\{?(?:sonnet|opus|haiku)", source)
                )
                self.assertNotIn("model:**{sonnet|opus|haiku}**", source)

    def test_codex_dispatch_rule_explicitly_rejects_claude_commands(self) -> None:
        for relative in (
            "skills/coordinator/writing-task-md/SKILL.md",
            "skills/dispatch-task/SKILL.md",
            "skills/dev/assign/SKILL.md",
            "spec/task-authoring.md",
            "template/_project/docs-hub/00_shared-rules/model-strategy.md.template",
        ):
            source = self.read(relative)
            with self.subTest(relative=relative):
                self.assertIn("Codex", source)
                self.assertIn("/reasoning", source)
                self.assertTrue(
                    re.search(r"Codex[^\n]*禁止", source)
                    or re.search(r"Never emit[^\n]*Codex", source),
                    relative,
                )

    def test_codex_global_rules_force_the_deterministic_dispatch_skill(self) -> None:
        source = self.read("templates/global/codex-agents-rules.md")
        self.assertIn("$dispatch-task", source)
        self.assertIn("model-dispatch --provider codex", source)
        self.assertIn("默认只给任务内容", source)
        self.assertIn("--model-advice", source)
        self.assertIn("不改变后台受管 Agent", source)
        self.assertNotIn("stdout 原样作为模型/推理前缀", source)

    def test_dispatch_skill_covers_the_reported_short_instruction_path(self) -> None:
        source = self.read("skills/dispatch-task/SKILL.md")
        frontmatter = source.split("---", 2)[1]
        for trigger in ("给 Dev 发送", "continues an existing task", "model/reasoning tier"):
            with self.subTest(trigger=trigger):
                self.assertIn(trigger, frontmatter)
        self.assertIn("Paste the renderer's stdout verbatim", source)
        self.assertIn("gpt-5.6-sol", source)

    def test_provider_neutral_strategy_is_referenced_by_every_frontend(self) -> None:
        for stack in ("android", "ios", "flutter", "harmony"):
            source = self.read(f"template/{stack}/CLAUDE.md.template")
            with self.subTest(stack=stack):
                self.assertIn("capability_tier", source)
                self.assertIn("model-strategy.md", source)


if __name__ == "__main__":
    unittest.main()
