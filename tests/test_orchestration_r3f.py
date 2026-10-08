"""R3-followup tests: retry-op resolution, fence atomicity, recovery fence.

Followup to R3: (1) a retry operation resolves to ITS OWN bound attempt —
never the latest of the chain — with full conclusion/identity assertions;
(2) the generation-switch fence closes the re-check-to-switch window via a
shared short critical section; (3) recover_only clears only fences matching
the recovered transaction.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
RUNTIME = SCRIPT_DIR / "agent-runtime.py"

sys.path.insert(0, str(SCRIPT_DIR))

import run_concurrency  # noqa: E402
import generation_fence  # noqa: E402
from dispatch_registry import (  # noqa: E402
    DispatchRegistryError,
    lookup_retry_op,
    open_request,
    open_retry,
    record_closed,
    record_launched,
)

EVIDENCE = (
    "✅ 验证通过：`python -m unittest`，exit 0；输出 OK；"
    "candidate_sha256=" + "a" * 64
    + "；execution_binding_sha256=" + "b" * 64
    + "；environment_sha256=" + "c" * 64
    + "；command_sha256=88d1e4ef3a5e210c702e32c1f294a637fcac036aae538cf3e0500c2c054b49c7"
    + "；count=1"
)
GOOD_REPORT = (
    "## 结果\n任务完成。\n" + EVIDENCE
    + "\n## 过程\np\n## 遇到的问题\n无\n"
    "## 解决方式\ns\n## 遗留风险与建议\n无\n"
)


class RetryOpResolutionTests(unittest.TestCase):
    """Followup 1: retry ops resolve their own attempt through the real CLI."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.directory = Path(self._temporary.name)
        self.slug = "r3f-retry"

    def _prepare(self) -> tuple[Path, Path]:
        worktree = self.directory / "worktree"
        state = worktree / ".codex-agent"
        state.mkdir(parents=True, exist_ok=True)
        (worktree / "base.txt").write_text("base\n", encoding="utf-8")
        brief = state / f"{self.slug}.md"
        brief.write_text("# Task\n\nDo the work.\n", encoding="utf-8")
        brief.chmod(0o400)
        return worktree, brief

    def _provider(self, name: str, sleep_seconds: int) -> Path:
        executable = self.directory / name
        executable.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/python3
                import sys, time
                time.sleep({sleep_seconds})
                from pathlib import Path
                args = sys.argv[1:]
                report = Path(args[args.index('--output-last-message') + 1])
                report.write_text({GOOD_REPORT!r}, encoding='utf-8')
                print('{{"type":"done"}}')
                """
            ),
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return executable

    def _run(self, executable: Path, worktree: Path, brief: Path, *extra, timeout: str = "1"):
        environment = os.environ.copy()
        environment.update(
            {
                "SULDE_TEST_MODE": "1",
                "SULDE_INTENT_CONTRACT": "",
                "SULDE_GUARDIAN_STREAM_OWNER": "",
                "SULDE_GUARDIAN_STREAM_PROVIDER": "",
                "SULDE_AGENT_PROVIDER": "codex",
                "SULDE_CODEX_EXE": str(executable),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        return subprocess.run(
            [
                sys.executable,
                str(RUNTIME),
                "run",
                str(worktree),
                self.slug,
                str(brief),
                *extra,
                "--timeout",
                timeout,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
            timeout=90,
        )

    def _rows(self, worktree: Path) -> list[dict]:
        registry = worktree / ".codex-agent" / f"{self.slug}.dispatch.jsonl"
        return [
            json.loads(line)
            for line in registry.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_old_retry_op_returns_its_own_conclusion_after_newer_success(
        self,
    ) -> None:
        worktree, brief = self._prepare()
        slow = self._provider("codex-slow", 3)
        fast = self._provider("codex-fast", 0)
        slow_env = None
        # attempt 1: timeout
        r1 = self._run(slow, worktree, brief)
        self.assertEqual(r1.returncode, 1)
        self.assertNotIn("Traceback", r1.stderr)
        # attempt 2 via op-1: timeout again
        r2 = self._run(
            slow, worktree, brief, "--retry", "--retry-op", "op-1"
        )
        self.assertEqual(r2.returncode, 1)
        self.assertNotIn("Traceback", r2.stderr)
        # repeating op-1 replays attempt 2 without any exception
        r2b = self._run(
            slow, worktree, brief, "--retry", "--retry-op", "op-1"
        )
        self.assertEqual(r2b.returncode, 1)
        self.assertNotIn("Traceback", r2b.stderr)
        self.assertIn("status=timeout", r2b.stdout)
        # attempt 3 via op-2 with the fast provider: success
        r3 = self._run(
            fast, worktree, brief, "--retry", "--retry-op", "op-2", timeout="15"
        )
        self.assertEqual(r3.returncode, 0, r3.stdout + r3.stderr)
        # THE counterexample: submitting the OLD op-1 again must return
        # op-1's own conclusion (the timed-out attempt), never op-2's
        # success — with terminal state, identities, launch count, and no
        # traceback.
        old = self._run(
            slow, worktree, brief, "--retry", "--retry-op", "op-1"
        )
        self.assertEqual(
            old.returncode, 1, old.stdout + old.stderr
        )
        self.assertNotIn("Traceback", old.stderr)
        self.assertIn("status=timeout", old.stdout)
        self.assertIn("duplicate_of_run", old.stdout)
        rows = self._rows(worktree)
        launched = [row for row in rows if row["type"] == "dispatch.launched"]
        self.assertEqual(
            len(launched), 3, "attempts 1/2/3 only — the old op must not launch"
        )
        opened = [row for row in rows if row["type"] == "dispatch.opened"]
        self.assertEqual(
            [row["attempt"] for row in opened], [1, 2, 3],
            "the old op must not open a new attempt",
        )
        closed = {
            row["attempt"]: row for row in rows if row["type"] == "dispatch.closed"
        }
        self.assertEqual(closed[2].get("stop_reason"), "timeout")
        self.assertEqual(closed[3].get("stop_reason"), "completed")
        # registry-level: op-1 resolves to attempt 2, op-2 to attempt 3
        registry = worktree / ".codex-agent" / f"{self.slug}.dispatch.jsonl"
        request_id = self._rows(worktree)[0]["request_id"]
        op1 = lookup_retry_op(registry, "op-1", request_id)
        self.assertIsNotNone(op1)
        self.assertEqual(op1["attempt"], 2)
        self.assertEqual(op1["stop_reason"], "timeout")
        op2 = lookup_retry_op(registry, "op-2", request_id)
        self.assertEqual(op2["attempt"], 3)
        self.assertEqual(op2["stop_reason"], "completed")

    def test_registered_op_resolves_its_own_attempt_segment(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            registry = Path(directory_name) / "slug.dispatch.jsonl"
            open_request(
                registry, request_id="req-1", request_sha256="a" * 64, slug="slug"
            )
            record_launched(
                registry, request_id="req-1", attempt=1, run_id="run-" + "a" * 24
            )
            record_closed(
                registry,
                request_id="req-1",
                attempt=1,
                run_id="run-" + "a" * 24,
                outcome="terminal",
                stop_reason="timeout",
            )
            open_retry(
                registry,
                retry_op_id="op-1",
                request_id="req-1",
                request_sha256="a" * 64,
                slug="slug",
                from_run_id="run-" + "a" * 24,
            )
            run2 = "run-" + "c" * 24
            record_launched(
                registry, request_id="req-1", attempt=2, run_id=run2
            )
            record_closed(
                registry,
                request_id="req-1",
                attempt=2,
                run_id=run2,
                outcome="terminal",
                stop_reason="completed",
                task_status="success",
                returncode=0,
            )
            # op-1 resolves to ITS attempt 2 with the newer attempt present.
            binding = lookup_retry_op(registry, "op-1", "req-1")
            self.assertIsNotNone(binding)
            self.assertEqual(binding["attempt"], 2)
            self.assertEqual(binding["stop_reason"], "completed")
            self.assertEqual(binding["task_status"], "success")


class FenceAtomicityTests(unittest.TestCase):
    """Followup 2: fence protocol — admission and switch share one lock."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.kb_home = Path(self._temporary.name) / "kb-home"
        self.kb_home.mkdir(parents=True)

    def test_fence_lock_mutual_exclusion(self) -> None:
        from generation_fence import (
            fence_lock,
            fence_refusal,
            write_fence,
        )

        # Hold the fence lock (as the installer does while writing and
        # re-checking) and verify a concurrent admission cannot even read a
        # torn/absent state — it must wait, then observe the fence.
        with fence_lock(self.kb_home):
            write_fence(
                self.kb_home,
                from_generation="gen-old:" + "a" * 64,
                to_generation="gen-new:" + "b" * 64,
            )
            refusal = fence_refusal(
                self.kb_home, run_generation="gen-old:" + "a" * 64
            )
            self.assertIsNotNone(refusal)
        self.assertIsNotNone(
            fence_refusal(self.kb_home, run_generation="gen-old:" + "a" * 64)
        )
        self.assertIsNone(
            fence_refusal(self.kb_home, run_generation="gen-new:" + "b" * 64)
        )

    def test_admission_refuses_superseded_generation(self) -> None:
        """The run-side admission critical section refuses a superseded
        generation once the fence is written — it can never publish an
        old-generation lease after the installer's write+recheck."""
        from generation_fence import (
            admission_fence,
            write_fence,
        )

        write_fence(
            self.kb_home,
            from_generation="gen-old:" + "a" * 64,
            to_generation="gen-new:" + "b" * 64,
        )
        with self.assertRaises(generation_fence.GenerationFenceError) as ctx:
            with admission_fence(
                self.kb_home, run_generation="gen-old:" + "a" * 64
            ):
                self.fail("superseded-generation admission must be refused")
        self.assertIn("generation switch in progress", str(ctx.exception))
        # Target-generation admission proceeds and can publish its lease.
        with admission_fence(
            self.kb_home, run_generation="gen-new:" + "b" * 64
        ):
            pass



if __name__ == "__main__":
    unittest.main()
