from __future__ import annotations

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kb" / "lint-sedimentation.py"
PRECOMMIT = ROOT / "hooks" / "git-precommit" / "check_kb_lint.sh"
SPEC = importlib.util.spec_from_file_location("sulde_lint_sedimentation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
LINT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LINT)


VALID = """---
doc_id: work-model/staged-snapshot
container: work-model
platform: none
summary: 验证提交快照而不是工作区副本
sedimentation_schema: 2
problem_type: workflow
evidence_status: verified
---

# 提交快照边界

## 问题原型
提交前门禁必须检查真正进入提交的内容，不能被工作区里尚未暂存的新版本掩盖。

## 根因与证据
暂存区和工作区是两份不同快照，集成测试可稳定复现两者内容不一致的状态。

## 适用边界
适用于 Git pre-commit；显式校验单个路径时仍应检查当前工作区草稿。

## 判定样本

### 路由正例
- **输入**：暂存旧结构后在工作区补全新结构
- **预期**：apply
- **原因**：提交快照与工作区内容明确不同
- **来源**：observed

### 路由反例
- **输入**：只校验一个尚未准备提交的草稿文件
- **预期**：skip
- **原因**：显式草稿检查应读取工作区内容
- **来源**：constructed

### 执行合格例
- **做法或输出**：默认门禁拒绝暂存区中的旧结构
- **预期**：pass
- **原因**：真正提交的内容没有绕过结构契约
- **来源**：constructed

### 执行失败例
- **做法或输出**：工作区补全后门禁通过但暂存区仍是旧结构
- **预期**：fail
- **原因**：实际提交内容仍然违反契约
- **来源**：observed

## 正确做法
默认校验读取 Git index；显式路径校验读取工作区，分别服务提交门禁与编辑反馈。

## 消费与防复发
由 pre-commit 和本集成测试消费，阻止工作区内容掩盖暂存区缺口。
"""


INVALID_STAGED = """---
doc_id: work-model/staged-snapshot
container: work-model
platform: none
summary: 暂存内容缺少结构化沉淀契约
---

# 旧结构

## 正确做法
只有一个结论，没有问题语境、适用边界或正反样本。
"""


class LintSedimentationTests(unittest.TestCase):
    def run_lint(self, root: Path, *paths: str) -> tuple[int, str]:
        previous_root = LINT.ROOT
        output = io.StringIO()
        try:
            LINT.ROOT = root
            with mock.patch.object(sys, "argv", [str(SCRIPT), *paths]):
                with contextlib.redirect_stdout(output):
                    result = LINT.main()
        finally:
            LINT.ROOT = previous_root
        return result, output.getvalue()

    def test_default_reads_staged_snapshot_but_explicit_path_reads_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            schema_target = root / "templates" / "knowledge" / "schema.json"
            schema_target.parent.mkdir(parents=True)
            schema_target.write_text(
                (ROOT / "templates" / "knowledge" / "schema.json").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            document = root / "knowledge" / "work-model" / "snapshot.md"
            document.parent.mkdir(parents=True)
            document.write_text(INVALID_STAGED, encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "add", "--", document.relative_to(root).as_posix()],
                cwd=root,
                check=True,
            )
            document.write_text(VALID, encoding="utf-8")

            staged_result, staged_output = self.run_lint(root)
            working_result, working_output = self.run_lint(
                root, document.relative_to(root).as_posix()
            )

            self.assertEqual(staged_result, 1)
            self.assertIn("sedimentation_schema must be 2", staged_output)
            self.assertEqual(working_result, 0)
            self.assertIn("1 v2 document", working_output)

    def test_precommit_exports_no_bytecode_to_all_python_validators(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            standard = root / "knowledge" / "SEDIMENTATION-STANDARD.md"
            standard.parent.mkdir(parents=True)
            standard.write_text("# fixture\n", encoding="utf-8")
            staged = root / "scripts" / "kb" / "fixture.py"
            staged.parent.mkdir(parents=True)
            staged.write_text("# staged\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "add", "--", staged.relative_to(root).as_posix()],
                cwd=root,
                check=True,
            )

            shim_dir = root / "bin"
            shim_dir.mkdir()
            log = root / "python-environment.log"
            python = shim_dir / "python3"
            python.write_text(
                "#!/bin/sh\n"
                "printf '%s\\t%s\\n' \"${PYTHONDONTWRITEBYTECODE-}\" \"$*\" "
                '>> "$SULDE_TEST_LOG"\n',
                encoding="utf-8",
            )
            python.chmod(0o755)
            environment = os.environ.copy()
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            environment["PATH"] = f"{shim_dir}:/usr/bin:/bin"
            environment["SULDE_TEST_LOG"] = str(log)

            completed = subprocess.run(
                [str(PRECOMMIT)],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            calls = log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(calls), 3)
            self.assertTrue(all(call.startswith("1\t") for call in calls), calls)
            self.assertEqual(
                [call.split("\t", 1)[1] for call in calls],
                [
                    "scripts/kb/lint-frontmatter.py",
                    "scripts/kb/lint-sedimentation.py",
                    "scripts/kb/build-index-md.py --check",
                ],
            )


if __name__ == "__main__":
    unittest.main()
