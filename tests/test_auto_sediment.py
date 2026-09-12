#!/usr/bin/env python3
"""Isolated git/KB-home integration tests for auto-sediment."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from scripts.kb.file_lock import lock_exclusive_nonblocking, unlock
from tests.synthetic_sedimentation import write_examples


MOCK_LLM = r'''#!/usr/bin/env python3
import json
import os
import sys
import time

prompt = sys.stdin.read()
counter = os.environ.get("MOCK_LLM_COUNT")
if counter:
    try:
        count = int(open(counter, encoding="utf-8").read())
    except (FileNotFoundError, ValueError):
        count = 0
    with open(counter, "w", encoding="utf-8") as handle:
        handle.write(str(count + 1))

def emit(action, container="", target=None, doc_id=None, markdown="", reason="mock"):
    print(json.dumps({
        "action": action,
        "container": container,
        "target_doc_id": target,
        "doc_id": doc_id,
        "markdown": markdown,
        "reason": reason,
    }, ensure_ascii=False))

def v2_document(title, summary, error_text, cause_text, correct_text, *, doc_id="ap-9999", related="", extra=""):
    related_line = f"related: [{related}]\n" if related else ""
    return f"""---
doc_id: {doc_id}
container: anti-patterns
platform: cross
summary: {summary}
sedimentation_schema: 2
problem_type: bug-fix
evidence_status: verified
{related_line}---

# {title}

## 问题原型
在受控知识写入任务中出现可观察偏差，期望形成可审计闭环，实际结果未满足约束。{extra}

## ❌ 错误
{error_text}

## 为什么错
{cause_text}；测试证据已经复现该行为并排除了无关的排版差异。

## 适用边界
适用于知识生成和合并；只读检索且不产生知识写入时不适用，证据不足时保留存疑。

## 判定样本

### 路由正例
- **输入**：自动生成知识条目但没有审稿与验证闭环
- **预期**：apply
- **原因**：命中受控知识写入条件
- **来源**：observed

### 路由反例
- **输入**：只读查询现有知识且不修改任何条目
- **预期**：skip
- **原因**：没有发生知识写入动作
- **来源**：constructed

### 执行合格例
- **做法或输出**：生成审稿分支并通过结构和证据门禁
- **预期**：pass
- **原因**：形成可回读的验证闭环
- **来源**：observed

### 执行失败例
- **做法或输出**：只写一段结论就直接宣称沉淀完成
- **预期**：fail
- **原因**：缺少边界样本和实际验收证据
- **来源**：observed

## ✅ 正确
{correct_text}，并用独立读取与回归测试确认结果。

## 消费与防复发
由沉淀 Skill、结构校验器和集成测试共同消费；主观语义仍交由人工审查。
"""

if "SLOW_CANDIDATE" in prompt:
    time.sleep(float(os.environ.get("MOCK_LLM_SLEEP", "1")))
    emit("unsure", reason="mock sleep completed")
elif "BAD_CANDIDATE" in prompt:
    print("not-json")
elif "合并成文器" in prompt:
    emit(
        "merge",
        "anti-patterns",
        "ap-0028",
        markdown=v2_document(
            "0028 — Synthetic merge boundary",
            "Synthetic merge preserves explicit boundaries",
            "身份与分支职责发生错配，合并候选也未保留通用增量。",
            "身份边界没有绑定到实际执行分支",
            "保持身份与分支职责一致并保留合并候选的通用增量",
            doc_id="ap-0028",
        ),
    )
elif "DENY_CANDIDATE" in prompt:
    emit(
        "new",
        "anti-patterns",
        markdown=v2_document(
            "敏感内容",
            "FAKEPROJ 信息泄漏",
            "FAKEPROJ 内部标识进入了公开知识内容。",
            "生成阶段没有执行脱敏检查",
            "先删除 FAKEPROJ 等内部标识再进入审稿",
        ),
    )
elif "NEW_CANDIDATE" in prompt:
    emit(
        "new",
        "anti-patterns",
        markdown=v2_document(
            "自动沉淀测试条目",
            "自动沉淀新条目的测试症状",
            "忽略机械防线并直接修改知识真源。",
            "知识写入没有形成可审计链路",
            "先产出隔离审稿分支",
            related="ap-0028",
        ),
    )
elif "SECRET_CANDIDATE" in prompt:
    emit(
        "new",
        "anti-patterns",
        markdown=v2_document(
            "密钥测试",
            "密钥形态必须被拦截",
            "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890 被写进知识正文。",
            "生成阶段没有执行密钥扫描",
            "检测到密钥形态时拒绝写入并保留审计证据",
        ),
    )
elif "MERGE_CANDIDATE" in prompt:
    emit("merge", "anti-patterns", "ap-0028")
elif "SKIP_CANDIDATE" in prompt:
    emit("skip", target="ap-0028")
else:
    emit("unsure", reason="留人工确认")
'''


MOCK_KB_INDEX = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

command = Path(__file__).stem
if command == "search":
    print(json.dumps([]))
    raise SystemExit(0)
if command == "build":
    if os.environ.get("MOCK_KB_BUILD_FAIL"):
        print("mock kb-index build failed", file=sys.stderr)
        raise SystemExit(9)
    print("mock kb-index build passed")
    raise SystemExit(0)
raise SystemExit(2)
'''


class AutoSedimentIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo"
        self.home = self.base / "kb-home"
        self.home.mkdir()
        # Construct a standalone repository, never clone private history or corpus.
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "--template=", "-b", "main", str(self.repo)], check=True)
        subprocess.run(["git", "config", "user.name", "Auto Sediment Test"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "auto-sediment@example.invalid"],
            cwd=self.repo,
            check=True,
        )
        installed_scripts = (
            "hooks/lib/kb_cli.py",
            "hooks/lib/prompt_noise.py",
            "hooks/lib/session_identity.py",
            "scripts/kb/auto-sediment.py",
            "scripts/kb/build-index-md.py",
            "scripts/kb/build-corpus-manifest.py",
            "scripts/kb/command_template.py",
            "scripts/kb/file_lock.py",
            "scripts/kb/kb-deny-lint.py",
            "scripts/kb/lint-frontmatter.py",
            "scripts/kb/lint-sedimentation.py",
            "scripts/kb/mem-secret-scan.py",
            "scripts/kb/memory_annotation.py",
            "scripts/kb/sedimentation_schema.py",
            "scripts/kb/l2-draft.py",
            "tools/kb-index/common.py",
            "tools/kb-index/corpus_manifest.py",
            "tools/kb-index/memory.py",
            "skills/sediment/SKILL.md",
            "templates/knowledge/schema.json",
            "templates/knowledge/anti-pattern.md",
            "templates/knowledge/platform-kb.md",
            "templates/knowledge/tech-docs.md",
            "templates/knowledge/case-studies.md",
            "templates/knowledge/work-model.md",
        )
        for relative in installed_scripts:
            source = ROOT / relative
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        _, examples = write_examples(self.base / "synthetic-examples")
        existing = examples["work-model/synthetic-range-0"].read_text(encoding="utf-8")
        existing = existing.replace("work-model/synthetic-range-0", "ap-0028").replace(
            "container: work-model", "container: anti-patterns")
        knowledge = self.repo / "knowledge/anti-patterns"
        knowledge.mkdir(parents=True)
        (knowledge / "0028-synthetic-existing.md").write_text(existing, encoding="utf-8")
        (self.repo / "knowledge/INDEX.md").write_text(
            "# Synthetic knowledge index\n\n## anti-patterns\n\n- ap-0028 Synthetic interval rule\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", *installed_scripts, "knowledge"],
            cwd=self.repo,
            check=True,
        )
        if subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=self.repo, check=False
        ).returncode:
            subprocess.run(
                ["git", "commit", "--quiet", "-m", "test: install auto-sediment"],
                cwd=self.repo,
                check=True,
            )
        self.mock_llm = self.base / "mock-llm.py"
        self.mock_llm.write_text(MOCK_LLM, encoding="utf-8")
        self.mock_llm_cmd = shlex.join([sys.executable, str(self.mock_llm)])
        self.mock_kb_root = self.base / "mock-kb-index"
        self.mock_kb_root.mkdir()
        for command in ("build", "search"):
            (self.mock_kb_root / f"{command}.py").write_text(
                MOCK_KB_INDEX, encoding="utf-8"
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_candidates(self, *lessons: str) -> None:
        text = "# candidates\n\n" + "".join(
            f"- {lesson}（待 /sediment 人工处理）\n" for lesson in lessons
        )
        (self.home / "distill-candidates.md").write_text(text, encoding="utf-8")

    def run_auto(
        self,
        maximum: int = 5,
        extra_environment: dict[str, str] | None = None,
        extra_arguments: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = str(self.home)
        environment["PYTHONIOENCODING"] = "utf-8"
        if extra_environment:
            environment.update(extra_environment)
        arguments = [
                sys.executable,
                "scripts/kb/auto-sediment.py",
                "--max-candidates",
                str(maximum),
                "--llm-cmd",
                self.mock_llm_cmd,
                "--kb-index-root",
                str(self.mock_kb_root),
                "--kb-index-python",
                sys.executable,
            ]
        if extra_arguments:
            arguments.extend(extra_arguments)
        return subprocess.run(
            arguments,
            cwd=self.repo,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

    def branch_name_prefix(self) -> str:
        return f"auto-sediment/{datetime.now().astimezone().strftime('%Y%m%d')}"

    def surgery_branch(self, output: str) -> str:
        match = re.search(r"\bbranch=(auto-sediment/\S+)", output)
        self.assertIsNotNone(match, output)
        return match.group(1)

    def run_id(self, output: str) -> str:
        match = re.search(r"\brun_id=(\d{8}-\d{6})\b", output)
        self.assertIsNotNone(match, output)
        return match.group(1)

    def decision_records(self, run_id: str) -> list[dict]:
        path = self.home / "sediment-runs" / f"decisions-{run_id}.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def sediment_pending(self) -> int:
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = str(self.home)
        completed = subprocess.run(
            [sys.executable, "scripts/kb/l2-draft.py", "--refresh"],
            cwd=self.repo,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 1, completed.stderr + completed.stdout)
        registry = json.loads((self.home / "l2" / "registry.json").read_text(encoding="utf-8"))
        return registry["channels"]["sediment_draft"]["pending"]

    def test_new_creates_numbered_document_branch_commit_and_marker(self) -> None:
        self.write_candidates("NEW_CANDIDATE 根因：缺少审稿分支")
        before = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
        completed = self.run_auto()
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("new=1 merge=0 skip=0 unsure=0", completed.stdout)
        self.assertEqual(
            subprocess.check_output(
                ["git", "branch", "--show-current"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).strip(),
            "main",
        )
        branch = self.surgery_branch(completed.stdout)
        self.assertTrue(branch.startswith(self.branch_name_prefix()))
        main_after = subprocess.check_output(
            ["git", "rev-parse", "main"],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
        surgery_after = subprocess.check_output(
            ["git", "rev-parse", branch],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
        self.assertEqual(before, main_after)
        self.assertNotEqual(before, surgery_after)
        paths = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", branch, "--", "knowledge/anti-patterns"],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        created = [path for path in paths if path.endswith("-auto-sediment.md")]
        self.assertEqual(len(created), 1)
        rendered = subprocess.check_output(
            ["git", "show", f"{branch}:{created[0]}"],
            cwd=self.repo,
            encoding="utf-8",
            errors="replace",
        )
        self.assertIn("sedimented_by: auto", rendered)
        self.assertRegex(rendered, r'doc_id: "ap-\d{4}"')
        reverse = subprocess.check_output(
            ["git", "show", f"{branch}:knowledge/anti-patterns/0028-synthetic-existing.md"],
            cwd=self.repo,
            encoding="utf-8",
            errors="replace",
        )
        created_id = re.search(r'doc_id: "(ap-\d{4})"', rendered).group(1)
        self.assertIn(created_id, reverse)
        self.assertIn("✅ 已沉淀 ap-", (self.home / "distill-candidates.md").read_text(encoding="utf-8"))
        self.assertTrue((self.home / "auto-sediment.log").is_file())

    def test_merge_skip_and_unsure_have_correct_effects(self) -> None:
        self.write_candidates("MERGE_CANDIDATE", "SKIP_CANDIDATE", "UNSURE_CANDIDATE")
        before = subprocess.check_output(
            ["git", "rev-parse", "main"],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
        completed = self.run_auto()
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        branch = self.surgery_branch(completed.stdout)
        self.assertEqual(
            subprocess.check_output(
                ["git", "rev-parse", "main"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).strip(),
            before,
        )
        self.assertNotEqual(
            subprocess.check_output(
                ["git", "rev-parse", branch],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).strip(),
            before,
        )
        target = subprocess.check_output(
            ["git", "show", f"{branch}:knowledge/anti-patterns/0028-synthetic-existing.md"],
            cwd=self.repo,
            encoding="utf-8",
            errors="replace",
        )
        self.assertIn("合并候选的通用增量", target)
        self.assertNotIn("sedimented_by: auto", target)
        message = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B", branch],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertIn("MERGE: MERGE_CANDIDATE -> ap-0028", message)
        candidates = (self.home / "distill-candidates.md").read_text(encoding="utf-8")
        self.assertIn("MERGE_CANDIDATE（✅ 已沉淀 ap-0028）", candidates)
        self.assertIn("SKIP_CANDIDATE（✅ 判重放弃:已有 ap-0028）", candidates)
        self.assertIn("UNSURE_CANDIDATE（❓ 证据不足待裁决）", candidates)

    def test_apply_failure_restores_original_branch_and_clean_worktree(self) -> None:
        self.write_candidates("NEW_CANDIDATE 根因：模拟 apply 中 build 抛错")
        before = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()

        completed = self.run_auto(extra_environment={"MOCK_KB_BUILD_FAIL": "1"})

        self.assertEqual(completed.returncode, 2, completed.stderr + completed.stdout)
        self.assertIn("kb-index build exited 9", completed.stderr)
        self.assertEqual(
            subprocess.check_output(
                ["git", "branch", "--show-current"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).strip(),
            "main",
        )
        self.assertEqual(
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).strip(),
            before,
        )
        self.assertEqual(
            subprocess.check_output(
                ["git", "status", "--porcelain=v1"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ),
            "",
        )
        self.assertIn(
            "待 /sediment 人工处理",
            (self.home / "distill-candidates.md").read_text(encoding="utf-8"),
        )

    def test_dirty_source_worktree_isolated_apply_preserves_progress(self) -> None:
        self.write_candidates("SKIP_CANDIDATE")
        dirty = self.repo / "developer-notes.txt"
        dirty.write_text("preserve this untracked work\n", encoding="utf-8")
        self.assertEqual(self.sediment_pending(), 1)

        completed = self.run_auto()

        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("new=0 merge=0 skip=1 unsure=0", completed.stdout)
        self.assertEqual(dirty.read_text(encoding="utf-8"), "preserve this untracked work\n")
        self.assertIn(
            "SKIP_CANDIDATE（✅ 判重放弃:已有 ap-0028）",
            (self.home / "distill-candidates.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(self.sediment_pending(), 0)
        self.assertEqual(
            subprocess.check_output(
                ["git", "worktree", "list", "--porcelain"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).count("worktree "),
            1,
        )

    def test_single_decision_failure_downgrades_to_unsure_without_blocking_batch(self) -> None:
        self.write_candidates("BAD_CANDIDATE", "SKIP_CANDIDATE")

        completed = self.run_auto()

        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("new=0 merge=0 skip=1 unsure=1", completed.stdout)
        candidates = (self.home / "distill-candidates.md").read_text(encoding="utf-8")
        self.assertIn("BAD_CANDIDATE（❓ 证据不足待裁决）", candidates)
        self.assertIn("SKIP_CANDIDATE（✅ 判重放弃:已有 ap-0028）", candidates)

    def test_deny_stops_without_commit_or_candidate_progress(self) -> None:
        self.write_candidates("DENY_CANDIDATE")
        (self.home / "sediment-deny.json").write_text(
            json.dumps({"patterns": ["FAKEPROJ"]}), encoding="utf-8"
        )
        before = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
        completed = self.run_auto()
        self.assertEqual(completed.returncode, 1, completed.stderr + completed.stdout)
        after = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
        self.assertEqual(before, after)
        self.assertIn(
            "待 /sediment 人工处理",
            (self.home / "distill-candidates.md").read_text(encoding="utf-8"),
        )

    def test_builtin_secret_patterns_apply_without_local_deny_file(self) -> None:
        self.write_candidates("SECRET_CANDIDATE")
        before = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
        completed = self.run_auto()
        self.assertEqual(completed.returncode, 1, completed.stderr + completed.stdout)
        after = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
        self.assertEqual(before, after)
        self.assertFalse((self.home / "sediment-deny.json").exists())
        self.assertIn(
            "待 /sediment 人工处理",
            (self.home / "distill-candidates.md").read_text(encoding="utf-8"),
        )

    def test_limit_lock_and_idempotent_empty_input(self) -> None:
        self.write_candidates(*(f"UNSURE_{number}" for number in range(6)))
        completed = self.run_auto(maximum=5)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        candidates = (self.home / "distill-candidates.md").read_text(encoding="utf-8")
        self.assertEqual(candidates.count("❓ 证据不足待裁决"), 5)
        self.assertEqual(candidates.count("待 /sediment 人工处理"), 1)

        second_home = self.base / "lock-home"
        second_home.mkdir()
        (second_home / "distill-candidates.md").write_text(
            "- UNSURE_LOCK（待 /sediment 人工处理）\n", encoding="utf-8"
        )
        lock = (second_home / "auto-sediment.lock").open("a+")
        lock_exclusive_nonblocking(lock)
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = str(second_home)
        environment["PYTHONIOENCODING"] = "utf-8"
        locked = subprocess.run(
            [sys.executable, "scripts/kb/auto-sediment.py", "--llm-cmd", self.mock_llm_cmd],
            cwd=self.repo,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        unlock(lock)
        lock.close()
        self.assertEqual(locked.returncode, 2)
        self.assertIn("another auto-sediment instance", locked.stderr)

        empty_home = self.base / "empty-home"
        empty_home.mkdir()
        (empty_home / "distill-candidates.md").write_text(
            "- done（❓ 存疑留人工）\n", encoding="utf-8"
        )
        environment["SULDE_KB_HOME"] = str(empty_home)
        empty = subprocess.run(
            [sys.executable, "scripts/kb/auto-sediment.py"],
            cwd=self.repo,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        self.assertEqual(empty.returncode, 0)
        self.assertIn("无待处理", empty.stdout)

    def test_decide_only_persists_one_jsonl_record_per_candidate(self) -> None:
        self.write_candidates("SKIP_CANDIDATE", "UNSURE_CANDIDATE")

        completed = self.run_auto(extra_arguments=["--decide-only"])

        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        run_id = self.run_id(completed.stdout)
        records = self.decision_records(run_id)
        self.assertEqual(len(records), 2)
        self.assertEqual([record["candidate_line_index"] for record in records], [2, 3])
        self.assertEqual(
            subprocess.check_output(
                ["git", "branch", "--show-current"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).strip(),
            "main",
        )
        self.assertIn("待 /sediment 人工处理", (self.home / "distill-candidates.md").read_text(encoding="utf-8"))

    def test_structured_problem_card_is_bound_to_persisted_decision(self) -> None:
        candidate_path = self.home / "distill-candidates.md"
        candidate_path.write_text(
            """# candidates

### Layer1 问题卡

- **问题类型**：workflow
- **任务与触发场景**：首次语境下生成受控知识
- **症状与差异**：实际没有审稿分支，期望形成隔离审稿
- **根因与证据缺口**：写入流程没有隔离边界
- **证据状态**：verified
- **一手证据 entry_id**：42
- **路由正例**（observed）：自动写知识但没有审稿分支
- **路由反例**（constructed）：只读检索现有知识
- **执行合格例**（constructed）：生成隔离分支并通过门禁
- **执行失败例**（observed）：直接修改主分支就宣称完成
- **沉淀候选**：NEW_CANDIDATE 根因：缺少审稿分支（待 /sediment 人工处理）
""",
            encoding="utf-8",
        )
        decided = self.run_auto(extra_arguments=["--decide-only"])
        self.assertEqual(decided.returncode, 0, decided.stderr + decided.stdout)
        run_id = self.run_id(decided.stdout)
        record = self.decision_records(run_id)[0]
        self.assertRegex(record["context_sha256"], r"^[0-9a-f]{64}$")

        candidate_path.write_text(
            candidate_path.read_text(encoding="utf-8").replace(
                "首次语境", "已被篡改的语境"
            ),
            encoding="utf-8",
        )
        applied = self.run_auto(extra_arguments=["--apply", run_id])

        self.assertEqual(applied.returncode, 2)
        self.assertIn("problem-card context changed", applied.stderr)
        self.assertNotIn(
            f"auto-sediment/{run_id}",
            subprocess.check_output(
                ["git", "branch", "--format=%(refname:short)"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).splitlines(),
        )

    def test_apply_uses_persisted_decision_to_create_branch_and_commit(self) -> None:
        self.write_candidates("NEW_CANDIDATE 根因：两阶段应用")
        counter = self.base / "llm-count.txt"
        environment = {"MOCK_LLM_COUNT": str(counter)}
        decided = self.run_auto(
            extra_environment=environment, extra_arguments=["--decide-only"]
        )
        self.assertEqual(decided.returncode, 0, decided.stderr + decided.stdout)
        run_id = self.run_id(decided.stdout)
        self.assertEqual(counter.read_text(encoding="utf-8"), "1")

        applied = self.run_auto(
            extra_environment=environment, extra_arguments=["--apply", run_id]
        )

        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        self.assertEqual(counter.read_text(encoding="utf-8"), "1")
        branch = self.surgery_branch(applied.stdout)
        self.assertEqual(branch, f"auto-sediment/{run_id}")
        self.assertIn(
            "chore(kb): auto-sediment candidates",
            subprocess.check_output(
                ["git", "log", "-1", "--pretty=%B", branch],
                cwd=self.repo,
                encoding="utf-8",
                errors="replace",
            ),
        )
        self.assertIn("✅ 已沉淀", (self.home / "distill-candidates.md").read_text(encoding="utf-8"))

    def test_resume_skips_persisted_indices_and_calls_llm_only_for_remaining(self) -> None:
        self.write_candidates("UNSURE_ONE", "UNSURE_TWO", "UNSURE_THREE")
        counter = self.base / "llm-count.txt"
        environment = {"MOCK_LLM_COUNT": str(counter)}
        first = self.run_auto(
            maximum=1,
            extra_environment=environment,
            extra_arguments=["--decide-only"],
        )
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        run_id = self.run_id(first.stdout)
        self.assertEqual(counter.read_text(encoding="utf-8"), "1")
        decision_path = self.home / "sediment-runs" / f"decisions-{run_id}.jsonl"
        with decision_path.open("ab") as handle:
            handle.write(b'{"candidate_line_index":')

        resumed = self.run_auto(
            maximum=3,
            extra_environment=environment,
            extra_arguments=["--resume", run_id],
        )

        self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
        self.assertIn("resume_skipped=1", resumed.stdout)
        self.assertEqual(counter.read_text(encoding="utf-8"), "3")
        self.assertEqual(len(self.decision_records(run_id)), 3)

    def test_per_candidate_timeout_downgrades_to_unsure_and_continues(self) -> None:
        self.write_candidates("SLOW_CANDIDATE", "SKIP_CANDIDATE")
        before = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()

        completed = self.run_auto(
            extra_environment={"MOCK_LLM_SLEEP": "1"},
            extra_arguments=["--per-candidate-timeout", "0.1"],
        )

        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("new=0 merge=0 skip=1 unsure=1", completed.stdout)
        records = self.decision_records(self.run_id(completed.stdout))
        self.assertIn("判定超时降级", records[0]["decision"]["reason"])
        candidates = (self.home / "distill-candidates.md").read_text(encoding="utf-8")
        self.assertIn("SLOW_CANDIDATE（❓ 证据不足待裁决）", candidates)
        self.assertIn("SKIP_CANDIDATE（✅ 判重放弃:已有 ap-0028）", candidates)
        self.assertIn("branch=none", completed.stdout)
        self.assertEqual(
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).strip(),
            before,
        )
        self.assertNotIn(
            f"auto-sediment/{self.run_id(completed.stdout)}",
            subprocess.check_output(
                ["git", "branch", "--format=%(refname:short)"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).splitlines(),
        )

    def test_repeated_apply_of_same_run_is_rejected(self) -> None:
        self.write_candidates("UNSURE_CANDIDATE")
        decided = self.run_auto(extra_arguments=["--decide-only"])
        self.assertEqual(decided.returncode, 0, decided.stderr + decided.stdout)
        run_id = self.run_id(decided.stdout)
        first = self.run_auto(extra_arguments=["--apply", run_id])
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        self.assertIn("branch=none", first.stdout)
        self.assertNotIn(
            f"auto-sediment/{run_id}",
            subprocess.check_output(
                ["git", "branch", "--format=%(refname:short)"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).splitlines(),
        )

        repeated = self.run_auto(extra_arguments=["--apply", run_id])

        self.assertEqual(repeated.returncode, 2, repeated.stderr + repeated.stdout)
        self.assertIn("candidate changed since decide", repeated.stderr)
        self.assertEqual(
            subprocess.check_output(
                ["git", "branch", "--show-current"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).strip(),
            "main",
        )

    def test_human_can_resolve_all_unsure_candidates_without_git_branch(self) -> None:
        self.write_candidates("UNSURE_ONE", "UNSURE_TWO")
        decided = self.run_auto(extra_arguments=["--decide-only"])
        self.assertEqual(decided.returncode, 0, decided.stderr + decided.stdout)
        run_id = self.run_id(decided.stdout)
        applied = self.run_auto(extra_arguments=["--apply", run_id])
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        self.assertIn("branch=none", applied.stdout)

        records = self.decision_records(run_id)
        resolution_file = self.base / "manual-resolutions.json"
        resolutions = [
            {
                "candidate_line_index": records[0]["candidate_line_index"],
                "lesson": records[0]["lesson"],
                "action": "merge",
                "target": "ap-0028",
                "reason": "human verified the lesson was merged into the canonical document",
            },
            {
                "candidate_line_index": records[1]["candidate_line_index"],
                "lesson": records[1]["lesson"],
                "action": "skip",
                "target": "resume-kit-skill/consistency-check.js",
                "reason": "human verified an external workflow already enforces this lesson",
            },
        ]
        resolution_file.write_text(
            json.dumps(resolutions, ensure_ascii=False), encoding="utf-8"
        )
        arguments = [
            "--resolve-manual",
            run_id,
            "--resolution-file",
            str(resolution_file),
            "--approved-by",
            "human-test",
        ]
        resolved = self.run_auto(extra_arguments=arguments)

        self.assertEqual(resolved.returncode, 0, resolved.stderr + resolved.stdout)
        self.assertIn("phase=manual-resolve resolved=2", resolved.stdout)
        self.assertIn("new=0 merge=1 skip=1 branch=none", resolved.stdout)
        candidates = (self.home / "distill-candidates.md").read_text(encoding="utf-8")
        self.assertIn("UNSURE_ONE（✅ 已沉淀 ap-0028）", candidates)
        self.assertIn(
            "UNSURE_TWO（✅ 判重放弃:已有 resume-kit-skill/consistency-check.js）",
            candidates,
        )
        audit_path = (
            self.home / "sediment-runs" / f"manual-resolutions-{run_id}.json"
        )
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        self.assertEqual(audit["run_id"], run_id)
        self.assertEqual(audit["approved_by"], "human-test")
        self.assertEqual(audit["resolutions"], resolutions)
        self.assertNotIn(
            f"auto-sediment/{run_id}",
            subprocess.check_output(
                ["git", "branch", "--format=%(refname:short)"],
                cwd=self.repo,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).splitlines(),
        )

        repeated = self.run_auto(extra_arguments=arguments)
        self.assertEqual(repeated.returncode, 0, repeated.stderr + repeated.stdout)
        log_records = [
            json.loads(line)
            for line in (self.home / "auto-sediment.log")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        manual_logs = [
            record
            for record in log_records
            if record.get("run_id") == run_id
            and record.get("phase") == "manual_resolve"
        ]
        self.assertEqual(len(manual_logs), 1)


if __name__ == "__main__":
    unittest.main()
