from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AgentOwnedHumanDecisionContractTests(unittest.TestCase):
    def test_operational_surfaces_do_not_delegate_mechanical_steps_to_people(self) -> None:
        surfaces = (
            "skills/sediment/SKILL.md",
            "skills/intent-guardian/SKILL.md",
            "skills/dev/assign/SKILL.md",
            "skills/dev/crash-fix/SKILL.md",
            "skills/dev/handoff/SKILL.md",
            "skills/dev/postmortem/SKILL.md",
            "skills/dev/ui-impl/SKILL.md",
            "skills/dev/ui-impl/references/android.md",
            "skills/dev/ui-impl/references/ios.md",
            "skills/coordinator/configure-sulde/SKILL.md",
            "skills/coordinator/update-design/SKILL.md",
            "skills/coordinator/sediment-from-code/SKILL.md",
            "skills/coordinator/coordinator-maintenance/SKILL.md",
            "skills/coordinator/multi-source-review/SKILL.md",
            "skills/coordinator/handoff-code-review/SKILL.md",
            "skills/coordinator/writing-task-md/SKILL.md",
            "scripts/kb/intent-guardian.py",
            "scripts/kb/self-repair.py",
            "docs/ONBOARDING.md",
            "docs/V0.2.0-DESIGN-v2.md",
            "docs/sulde-memory-design.md",
            "docs/intent-guardian.md",
            "docs/dual-runtime-contract.md",
            "docs/event-observability.md",
            "docs/cognee-selfhost/HANDOFF.md",
            "docs/GETTING_STARTED.md",
            "docs/superpowers/specs/2026-08-06-sulde-0.4.10-cross-platform-artifact-design.md",
            "docs/V0.2.0-DESIGN.md",
            "scripts/kb/sulde-status.py",
        )
        delegated_patterns = (
            r"请回复[：:]",
            r"然后回复[‘'\"]?好了",
            r"让用户(?:在[^\n]{0,80})?执行",
            r"让用户(?:在[^\n]{0,80})?回贴",
            r"只能由人在自己的终端执行",
            r"由人在终端执行",
            r"手动\s+(?:cp|mv|Edit)\b",
            r"需手动\s+(?:cp|mv|Edit)\b",
            r"按并入方案生成可审阅 diff",
            r"不要自动 push[^\n]*等用户",
            r"不自动提交[^\n]*等待用户",
            r"不 push[^\n]*等用户",
            r"用户自跑",
            r"用户自跑 WebFetch",
            r"是否执行修复\?\(y/n\)",
            r"run it manually from a human-controlled terminal",
            r"用户主动跑",
            r"监控指令\(派给用户\)",
            r"必须 user 主动",
            r"可手动 `/postmortem`",
            r"user `/ultrareview`",
            r"由人使用 `(?:rebind|retire)-workspace`",
            r"运行 intent-guardian\.py interventions 查看并人工处置",
            r"远端 push 留待用户另行确认",
            r"用户自填命令",
        )

        violations: list[str] = []
        for relative in surfaces:
            text = (ROOT / relative).read_text(encoding="utf-8")
            for pattern in delegated_patterns:
                if re.search(pattern, text):
                    violations.append(f"{relative}: {pattern}")
        self.assertEqual(violations, [])

    def test_sediment_routes_conclusive_mechanical_work_to_agent(self) -> None:
        instructions = (ROOT / "skills/sediment/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Agent 直接生成并入 diff", instructions)
        self.assertIn("Agent 直接按系列新增或全新条目处理", instructions)
        self.assertNotIn("让人决定并入", instructions)


if __name__ == "__main__":
    unittest.main()
