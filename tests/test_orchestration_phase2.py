"""Phase 2 (orchestration iteration) tests: usage accounting (C4) + recovery invariants (C5).

C4: incremental usage scanning with three-state accounting (complete /
lower_bound / unknown — missing is never zero), cross-run aggregation that
dedups by run identity, fail-closed truncation handling, and wiring through
the real CLI so timeout/failed runs still preserve observed usage.

C5: recovery stays attributed — usage/recovery artifacts from two sessions of
the same project never merge, and a run's usage gap never blocks its result.
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

REPORT = """## 结果
任务完成。
✅ 验证通过：`python -m unittest`，exit 0；输出 OK；candidate_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa；execution_binding_sha256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb；environment_sha256=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc；command_sha256=88d1e4ef3a5e210c702e32c1f294a637fcac036aae538cf3e0500c2c054b49c7；count=1
## 过程
执行最小改动。
## 遇到的问题
无。
## 解决方式
按任务书实现。
## 遗留风险与建议
无已知风险。
"""

sys.path.insert(0, str(SCRIPT_DIR))

from usage_ledger import (  # noqa: E402
    UsageLedgerError,
    aggregate_usage,
    merge_report_state,
    scan_usage,
    scan_usage_incremental,
)
import usage_ledger  # noqa: E402


def _write_stream(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"".join(
            json.dumps(line, sort_keys=True).encode("utf-8") + b"\n"
            for line in lines
        )
    )


def claude_turn(input_tokens: int, output_tokens: int) -> dict:
    return {
        "type": "assistant",
        "message": {
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 10,
            }
        },
    }


def claude_result(input_tokens: int, output_tokens: int) -> dict:
    return {
        "type": "result",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": 10,
            "cache_creation_input_tokens": 0,
        },
    }


def codex_token_count(input_tokens: int, output_tokens: int) -> dict:
    return {
        "type": "token_count",
        "info": {
            "total_token_usage": {
                "input_tokens": input_tokens,
                "cached_input_tokens": 0,
                "output_tokens": output_tokens,
            }
        },
    }


def make_report(path: Path, **overrides) -> dict:
    values = dict(
        provider="claude",
        run_id="run-" + "a" * 24,
        slug="slug",
    )
    values.update(overrides)
    return scan_usage(path, **values)


class UsageScanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.directory = Path(self._temporary.name)

    def test_claude_complete_stream_yields_complete_cumulative_values(self) -> None:
        events = self.directory / "events.jsonl"
        _write_stream(
            events,
            [
                {"type": "system", "subtype": "init"},
                claude_turn(100, 20),
                claude_result(350, 90),
            ],
        )
        report = make_report(events)
        self.assertEqual(report["state"], "complete")
        self.assertEqual(report["metrics"]["input_tokens"], {"value": 350, "state": "complete"})
        self.assertEqual(report["metrics"]["output_tokens"], {"value": 90, "state": "complete"})
        self.assertEqual(report["metrics"]["cached_input_tokens"]["value"], 10)

    def test_claude_timeout_without_result_is_a_lower_bound(self) -> None:
        events = self.directory / "events.jsonl"
        _write_stream(
            events,
            [claude_turn(100, 20), claude_turn(50, 10)],
        )
        report = make_report(events)
        self.assertEqual(report["state"], "lower_bound")
        self.assertEqual(report["metrics"]["input_tokens"]["value"], 150)
        self.assertEqual(report["metrics"]["input_tokens"]["state"], "lower_bound")
        self.assertEqual(report["metrics"]["output_tokens"]["value"], 30)

    def test_stream_without_usage_is_unknown_and_never_zero(self) -> None:
        events = self.directory / "events.jsonl"
        _write_stream(events, [{"type": "system", "subtype": "init"}])
        report = make_report(events)
        self.assertEqual(report["state"], "unknown")
        for metric in report["metrics"].values():
            self.assertIsNone(metric["value"])
            self.assertEqual(metric["state"], "unknown")

    def test_codex_token_count_totals_are_recognized(self) -> None:
        events = self.directory / "events.jsonl"
        _write_stream(events, [codex_token_count(500, 120)])
        report = make_report(events, provider="codex")
        self.assertEqual(report["state"], "complete")
        self.assertEqual(report["metrics"]["input_tokens"]["value"], 500)
        self.assertEqual(report["metrics"]["output_tokens"]["value"], 120)

    def test_real_codex_turn_completed_usage_is_recognized_as_cumulative(self) -> None:
        # Shape taken from the R1-05 evidence sample (values simplified):
        # {"type": "turn.completed", "usage": {...thread totals...}}
        events = self.directory / "events.jsonl"
        _write_stream(
            events,
            [
                {"type": "thread.started", "thread_id": "01a0d65f"},
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 516328,
                        "cached_input_tokens": 462720,
                        "cache_write_input_tokens": 0,
                        "output_tokens": 8651,
                        "reasoning_output_tokens": 672,
                    },
                },
            ],
        )
        report = make_report(events, provider="codex")
        self.assertEqual(report["state"], "complete")
        self.assertEqual(report["basis"], "cumulative")
        self.assertEqual(report["metrics"]["input_tokens"]["value"], 516328)
        self.assertEqual(report["metrics"]["cached_input_tokens"]["value"], 462720)
        self.assertEqual(report["metrics"]["output_tokens"]["value"], 8651)
        self.assertEqual(report["metrics"]["cache_write_input_tokens"]["value"], 0)

    def test_incremental_cursor_persists_and_accumulates(self) -> None:
        # R1-05: 100 observed, then 20 appended, same run aggregate = 120.
        events = self.directory / "events.jsonl"
        cursor = self.directory / "usage-cursor.json"
        _write_stream(events, [claude_turn(100, 20)])
        first, _state = scan_usage_incremental(
            events, cursor, provider="claude", run_id="run-" + "a" * 24, slug="slug"
        )
        self.assertEqual(first["metrics"]["input_tokens"]["value"], 100)
        with events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(claude_turn(20, 2)) + "\n")
        second, _state = scan_usage_incremental(
            events, cursor, provider="claude", run_id="run-" + "a" * 24, slug="slug"
        )
        self.assertEqual(second["metrics"]["input_tokens"]["value"], 120)
        self.assertEqual(second["state"], "lower_bound")
        # No new data keeps the previous values verbatim.
        third, _state = scan_usage_incremental(
            events, cursor, provider="claude", run_id="run-" + "a" * 24, slug="slug"
        )
        self.assertEqual(third["metrics"]["input_tokens"]["value"], 120)

    def test_out_of_order_cumulative_is_ignored_not_applied(self) -> None:
        events = self.directory / "events.jsonl"
        cursor = self.directory / "usage-cursor.json"
        _write_stream(
            events,
            [
                codex_token_count(500, 100),
            ],
        )
        first, _state = scan_usage_incremental(
            events, cursor, provider="codex", run_id="run-" + "b" * 24, slug="slug"
        )
        self.assertEqual(first["metrics"]["input_tokens"]["value"], 500)
        # A smaller late cumulative is stale history: ignored.
        with events.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 10, "output_tokens": 1},
                    }
                )
                + "\n"
            )
        second, _state = scan_usage_incremental(
            events, cursor, provider="codex", run_id="run-" + "b" * 24, slug="slug"
        )
        self.assertEqual(second["metrics"]["input_tokens"]["value"], 500)
        self.assertEqual(second["out_of_order_ignored"], 1)

    def test_rotated_stream_preserves_prior_totals(self) -> None:
        events = self.directory / "events.jsonl"
        cursor = self.directory / "usage-cursor.json"
        _write_stream(events, [claude_result(300, 40)])
        first, _state = scan_usage_incremental(
            events, cursor, provider="claude", run_id="run-" + "c" * 24, slug="slug"
        )
        self.assertEqual(first["state"], "complete")
        # Rotation: the old stream is replaced by a genuinely new file
        # (new inode), starting from zero.
        events.unlink()
        _write_stream(events, [claude_turn(7, 1)])
        second, _state = scan_usage_incremental(
            events, cursor, provider="claude", run_id="run-" + "c" * 24, slug="slug"
        )
        self.assertEqual(second["stream_generation"], 2)
        self.assertEqual(len(second["prior_streams"]), 1)
        self.assertEqual(
            second["prior_streams"][0]["metrics"]["input_tokens"]["value"], 300
        )
        self.assertEqual(second["metrics"]["input_tokens"]["value"], 7)

    def test_codex_event_msg_payload_variant_is_recognized(self) -> None:
        events = self.directory / "events.jsonl"
        _write_stream(
            events,
            [
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "total_token_usage": {
                            "input_tokens": 42,
                            "output_tokens": 7,
                        },
                    },
                }
            ],
        )
        report = make_report(events, provider="codex")
        self.assertEqual(report["state"], "complete")
        self.assertEqual(report["metrics"]["input_tokens"]["value"], 42)

    def test_incremental_scans_equal_single_scan(self) -> None:
        events = self.directory / "events.jsonl"
        cursor = self.directory / "usage-cursor.json"
        _write_stream(events, [claude_turn(100, 20)])
        first, _state = scan_usage_incremental(
            events, cursor, provider="claude", run_id="run-" + "a" * 24, slug="slug"
        )
        self.assertEqual(first["state"], "lower_bound")
        with events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(claude_result(350, 90)) + "\n")
        second, _state = scan_usage_incremental(
            events, cursor, provider="claude", run_id="run-" + "a" * 24, slug="slug"
        )
        self.assertEqual(second["state"], "complete")
        self.assertEqual(second["metrics"]["input_tokens"]["value"], 350)

    def test_truncated_stream_fails_closed(self) -> None:
        events = self.directory / "events.jsonl"
        cursor = self.directory / "usage-cursor.json"
        _write_stream(events, [claude_turn(100, 20)])
        first, _state = scan_usage_incremental(
            events, cursor, provider="claude", run_id="run-" + "a" * 24, slug="slug"
        )
        _write_stream(events, [claude_turn(1, 1)])
        with self.assertRaises(UsageLedgerError):
            scan_usage_incremental(
                events, cursor, provider="claude", run_id="run-" + "a" * 24, slug="slug"
            )

    def test_torn_tail_is_ignored_not_parsed(self) -> None:
        events = self.directory / "events.jsonl"
        _write_stream(events, [claude_turn(100, 20)])
        with events.open("ab") as handle:
            handle.write(json.dumps(claude_result(350, 90)).encode()[:20])
        report = make_report(events)
        self.assertEqual(report["state"], "lower_bound")
        self.assertEqual(report["metrics"]["input_tokens"]["value"], 100)

    def test_tool_events_and_secrets_are_not_collected(self) -> None:
        events = self.directory / "events.jsonl"
        _write_stream(
            events,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "cat ~/.ssh/id_rsa"},
                            }
                        ],
                        "usage": {"input_tokens": 10, "output_tokens": 5},
                    },
                }
            ],
        )
        # A single assistant turn is per-turn evidence, i.e. a floor.
        report = make_report(events)
        self.assertEqual(report["state"], "lower_bound")
        self.assertEqual(report["metrics"]["input_tokens"]["value"], 10)
        encoded = json.dumps(report)
        self.assertNotIn("ssh", encoded)
        self.assertNotIn("cat ~/.ssh", encoded)
        self.assertNotIn("id_rsa", encoded)


class UsageAggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.directory = Path(self._temporary.name)

    def _report(self, run_suffix: str, state: str, input_value) -> dict:
        events = self.directory / f"{run_suffix}.jsonl"
        lines: list[dict] = []
        if state == "complete":
            lines.append(claude_result(input_value, 10))
        elif state == "lower_bound":
            lines.append(claude_turn(input_value, 10))
        _write_stream(events, lines)
        return scan_usage(
            events,
            provider="claude",
            run_id="run-" + run_suffix.encode().hex().rjust(24, "0")[-24:],
            slug="slug",
        )

    def test_same_run_reported_twice_is_counted_once(self) -> None:
        events = self.directory / "dedup.jsonl"
        _write_stream(events, [claude_result(100, 10)])
        report = scan_usage(
            events, provider="claude", run_id="run-" + "a" * 24, slug="slug"
        )
        aggregate = aggregate_usage([report, report, report])
        self.assertEqual(aggregate["run_count"], 1)
        self.assertEqual(aggregate["metrics"]["input_tokens"]["value"], 100)

    def test_independent_runs_sum_without_merging(self) -> None:
        first = self._report("runone", "complete", 100)
        second = self._report("runtwo", "complete", 70)
        aggregate = aggregate_usage([first, second])
        self.assertEqual(aggregate["run_count"], 2)
        self.assertEqual(aggregate["state"], "complete")
        self.assertEqual(aggregate["metrics"]["input_tokens"]["value"], 170)

    def test_unknown_contributor_degrades_completeness(self) -> None:
        complete = self._report("runone", "complete", 100)
        unknown = self._report("runtwo", "unknown", None)
        aggregate = aggregate_usage([complete, unknown])
        self.assertEqual(aggregate["run_count"], 2)
        self.assertEqual(aggregate["metrics"]["input_tokens"]["state"], "lower_bound")
        self.assertEqual(aggregate["metrics"]["input_tokens"]["value"], 100)
        self.assertEqual(aggregate["state"], "lower_bound")

    def test_state_merge_ladder(self) -> None:
        self.assertEqual(merge_report_state(), "unknown")
        self.assertEqual(merge_report_state("unknown", "unknown"), "unknown")
        self.assertEqual(merge_report_state("complete", "complete"), "complete")
        # Partial knowledge (one complete run, one unknown run) is a floor.
        self.assertEqual(merge_report_state("complete", "unknown"), "lower_bound")
        self.assertEqual(merge_report_state("complete", "lower_bound"), "lower_bound")


class CliUsageIntegrationTests(unittest.TestCase):
    """Real CLI runs (fake provider, zero paid model calls)."""

    def setUp(self) -> None:
        self.environment_patch = mock.patch.dict(
            os.environ,
            {
                "SULDE_TEST_MODE": "1",
                "SULDE_INTENT_CONTRACT": "",
                "SULDE_GUARDIAN_STREAM_OWNER": "",
                "SULDE_GUARDIAN_STREAM_PROVIDER": "",
            },
            clear=False,
        )
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)

    def prepare(self, directory: Path, slug: str) -> tuple[Path, Path]:
        worktree = directory / "worktree"
        state = worktree / ".codex-agent"
        state.mkdir(parents=True)
        (worktree / "base.txt").write_text("base\n", encoding="utf-8")
        brief = state / f"{slug}.md"
        brief.write_text("# Task\n\nDo the work.\n", encoding="utf-8")
        brief.chmod(0o400)
        return worktree, brief

    def write_provider_executable(
        self,
        directory: Path,
        *,
        usage_lines: str = '{"type":"token_count","info":{"total_token_usage":{"input_tokens":1234,"cached_input_tokens":10,"output_tokens":77}}}',
        sleep_seconds: int = 0,
    ) -> Path:
        executable = directory / "codex"
        executable.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/python3
                import sys, time
                from pathlib import Path
                args = sys.argv[1:]
                print({usage_lines!r}, flush=True)
                if {sleep_seconds}:
                    time.sleep({sleep_seconds})
                report = Path(args[args.index('--output-last-message') + 1])
                report.write_text({REPORT!r}, encoding='utf-8')
                print('{{"type":"done"}}')
                """
            ),
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return executable

    def _run_cli(self, worktree: Path, slug: str, brief: Path, environment: dict, timeout: str = "15"):
        return subprocess.run(
            [
                sys.executable,
                str(RUNTIME),
                "run",
                str(worktree),
                slug,
                str(brief),
                "--timeout",
                timeout,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
            timeout=60,
        )

    def test_successful_run_publishes_complete_usage_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "usage-ok")
            executable = self.write_provider_executable(directory)
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(executable),
                }
            )
            completed = self._run_cli(worktree, "usage-ok", brief, environment)
            state = worktree / ".codex-agent"
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            usage = json.loads((state / "usage-ok.usage.json").read_text(encoding="utf-8"))
            self.assertEqual(usage["schema"], "sulde-usage-report-v1")
            self.assertEqual(usage["state"], "complete")
            self.assertEqual(usage["metrics"]["input_tokens"]["value"], 1234)
            self.assertEqual(usage["metrics"]["cached_input_tokens"]["value"], 10)
            guardian = json.loads(
                (state / "usage-ok.guardian.json").read_text(encoding="utf-8")
            )
            embedded = guardian["execution"]["usage_report"]
            self.assertIsNotNone(embedded)
            self.assertEqual(embedded["metrics"]["output_tokens"]["value"], 77)

    def test_timed_out_run_preserves_observed_usage_as_lower_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "usage-timeout")
            executable = self.write_provider_executable(
                directory,
                usage_lines='{"type":"token_count","info":{"last_token_usage":{"input_tokens":55,"output_tokens":6}}}',
                sleep_seconds=6,
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(executable),
                }
            )
            completed = self._run_cli(worktree, "usage-timeout", brief, environment, timeout="1")
            self.assertIn("status=timeout", completed.stdout + completed.stderr)
            usage = json.loads(
                (worktree / ".codex-agent/usage-timeout.usage.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(usage["state"], "lower_bound")
            self.assertEqual(usage["metrics"]["input_tokens"]["value"], 55)
            self.assertEqual(usage["metrics"]["input_tokens"]["state"], "lower_bound")

    def test_two_sessions_same_project_stay_separate_and_dedup(self) -> None:
        """C5 attribution: two runs of one project never merge identities."""
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            reports = []
            for index, slug in enumerate(("session-a", "session-b")):
                worktree, brief = self.prepare(directory / slug, slug)
                executable = self.write_provider_executable(directory / slug)
                environment = os.environ.copy()
                environment.update(
                    {
                        "SULDE_AGENT_PROVIDER": "codex",
                        "SULDE_CODEX_EXE": str(executable),
                    }
                )
                completed = self._run_cli(worktree, slug, brief, environment)
                self.assertEqual(
                    completed.returncode, 0, completed.stdout + completed.stderr
                )
                reports.append(
                    json.loads(
                        (worktree / f".codex-agent/{slug}.usage.json").read_text(
                            encoding="utf-8"
                        )
                    )
                )
            self.assertNotEqual(reports[0]["run_id"], reports[1]["run_id"])
            self.assertNotEqual(reports[0]["slug"], reports[1]["slug"])
            aggregate = aggregate_usage(reports)
            self.assertEqual(aggregate["run_count"], 2)
            self.assertEqual(aggregate["metrics"]["input_tokens"]["value"], 2468)


if __name__ == "__main__":
    unittest.main()
