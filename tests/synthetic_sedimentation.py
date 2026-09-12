"""Construct scorer/parser fixtures; these are not a retrieval-quality corpus."""

from __future__ import annotations

import json
from pathlib import Path


def write_examples(root: Path) -> tuple[Path, dict[str, Path]]:
    """Create five synthetic documents and twenty separately worded queries."""
    root.mkdir(parents=True, exist_ok=True)
    themes = ("temperature range", "timer limit", "canvas dimensions", "storage capacity", "sample rate")
    rows = []
    paths = {}
    samples = (
        ("route", "apply", "路由正例", "输入", "A bounded {theme} value needs an explicit range check.",
         "Check whether a proposed {theme} exceeds a declared interval."),
        ("route", "skip", "路由反例", "输入", "Only the display label for {theme} is being translated.",
         "Renaming the caption of {theme} without changing its numeric behavior."),
        ("outcome", "pass", "执行合格例", "做法或输出", "The {theme} bounds and rejection case both match the test specification.",
         "Both valid and out-of-range {theme} inputs were checked against the expected result."),
        ("outcome", "fail", "执行失败例", "做法或输出", "The {theme} check accepts values outside its declared interval.",
         "An excessive {theme} value passes despite a documented maximum."),
    )
    for index, theme in enumerate(themes):
        doc_id = f"work-model/synthetic-range-{index}"
        text = (
            f"---\ndoc_id: {doc_id}\ncontainer: work-model\nplatform: none\n"
            f"summary: Synthetic {theme} fixture for scorer tests\n"
            "sedimentation_schema: 2\nproblem_type: workflow\nevidence_status: verified\n---\n\n"
            f"# Synthetic {theme} specification\n\n"
            "## 问题原型\n\nThis independently constructed example exercises a bounded numeric check.\n\n"
            "## 根因与证据\n\nThe synthetic specification supplies both accepted and rejected values. "
            "It describes no production incident and makes no real search-quality claim.\n\n"
            "## 适用边界\n\nApply to numeric range behavior, not caption-only changes.\n\n"
            "## 判定样本\n\n"
        )
        for kind, expected, heading, field, source_input, query in samples:
            text += (f"### {heading}\n\n- **{field}**：{source_input.format(theme=theme)}\n"
                     f"- **预期**：{expected}\n- **原因**：Compare only the constructed interval behavior.\n"
                     "- **来源**：constructed\n\n")
            rows.append({"case_id": f"synthetic-{index}-{expected}", "kind": kind,
                         "query": query.format(theme=theme), "expected_doc_id": doc_id,
                         "expected": expected, "note": "Synthetic scorer fixture, not production retrieval evidence"})
        text += ("## 正确做法\n\nEvaluate valid and invalid values against the explicit specification.\n\n"
                 "## 消费与防复发\n\nThe parser and scoring tests consume only these synthetic fixtures.\n")
        path = root / f"synthetic-{index}.md"
        path.write_text(text, encoding="utf-8")
        paths[doc_id] = path
    data = root / "synthetic-paraphrases.jsonl"
    data.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return data, paths
