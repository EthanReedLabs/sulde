from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from sedimentation_schema import (  # noqa: E402
    extract_samples,
    guidance_excerpt,
    load_schema,
    validate_document,
)


VALID = """---
doc_id: work-model/structured-example
container: work-model
platform: none
summary: 结构化沉淀测试样本
sedimentation_schema: 2
problem_type: workflow
evidence_status: verified
---

# 结构化沉淀测试样本

## 问题原型

在需要跨会话复用的工程任务中，只有结论而没有问题语境，后续执行无法判断是否同类。

## 根因与证据

根因是知识没有记录判定边界；集成测试复现了相似输入被错误应用的结果。

## 适用边界

适用于跨项目规则；仅记录当前分支状态时不适用，信息不足时先继续收集证据。

## 判定样本

### 路由正例

**输入**：同类任务中 Agent 反复不知道什么时候应用已经记录的规则
**预期**：apply
**原因**：命中跨会话复用和规则判定两个必要条件
**来源**：observed

### 路由反例

| 输入 | 预期 | 原因 | 来源 |
|---|---|---|---|
| 只记录当前分支下一步待办 | skip | 属于项目私有状态而非通用知识 | constructed |

### 执行合格例

- **做法或输出**：写清问题语境、边界、四类样本并连接实际消费者
- **预期**：pass
- **原因**：检索和验收均有可回读依据
- **来源**：constructed

### 执行失败例

- **做法或输出**：只有错误、原因和正确三段就宣称已经完整沉淀
- **预期**：fail
- **原因**：没有解决是否适用和如何验收的问题
- **来源**：observed

## 正确做法

先建立 Layer1 问题卡，再脱敏为带四类样本的 Layer2 文档并运行回归验证。

## 消费与防复发

由沉淀 Skill、检索器、意图监督器和结构门禁共同消费，主观语义保留人工审查。
"""


class SedimentationSchemaTests(unittest.TestCase):
    def test_all_container_templates_are_declared_and_present(self) -> None:
        schema = load_schema(ROOT)
        self.assertEqual(schema["schema"], "sulde-sedimentation-v2")
        self.assertEqual(
            set(schema["container_templates"]),
            {"anti-patterns", "platform-kb", "tech-docs", "case-studies", "work-model"},
        )
        for template in schema["container_templates"].values():
            self.assertTrue((ROOT / "templates" / "knowledge" / template).is_file())
        self.assertTrue((ROOT / "templates" / "knowledge" / "problem-card.md").is_file())

    def test_valid_document_accepts_mixed_markdown_shapes(self) -> None:
        self.assertEqual(validate_document(VALID, root=ROOT, require_v2=True), [])
        samples = {sample.role: sample for sample in extract_samples(VALID)}
        self.assertEqual(samples["route_positive"].expected, "apply")
        self.assertEqual(samples["route_negative"].expected, "skip")
        self.assertEqual(samples["outcome_positive"].expected, "pass")
        self.assertEqual(samples["outcome_negative"].expected, "fail")

    def test_wrong_polarity_is_rejected(self) -> None:
        errors = validate_document(
            VALID.replace(
                "| 只记录当前分支下一步待办 | skip |",
                "| 只记录当前分支下一步待办 | apply |",
                1,
            ),
            root=ROOT,
            require_v2=True,
        )
        self.assertIn("route_negative expected must be skip", errors)

    def test_missing_semantic_role_is_rejected(self) -> None:
        start = VALID.index("### 执行失败例")
        end = VALID.index("## 正确做法")
        errors = validate_document(
            VALID[:start] + VALID[end:], root=ROOT, require_v2=True
        )
        self.assertIn("missing semantic section: outcome_negative", errors)

    def test_inconclusive_requires_explicit_missing_evidence(self) -> None:
        errors = validate_document(
            VALID.replace("evidence_status: verified", "evidence_status: inconclusive"),
            root=ROOT,
            require_v2=True,
        )
        self.assertIn(
            "inconclusive knowledge must state the missing evidence in root_cause",
            errors,
        )

    def test_guardian_excerpt_keeps_boundaries_and_samples(self) -> None:
        excerpt = guidance_excerpt(VALID)
        self.assertIn("## 适用边界", excerpt)
        self.assertIn("### 路由反例", excerpt)
        self.assertIn("### 执行失败例", excerpt)
        self.assertNotIn("## 问题原型", excerpt)


if __name__ == "__main__":
    unittest.main()
