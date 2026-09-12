from __future__ import annotations

import ast
import hashlib
import json
import runpy
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
HOOK_LIB = ROOT / "hooks" / "lib"
sys.path.insert(0, str(HOOK_LIB))

import recall_log  # noqa: E402


NOW = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)


def common_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "ts": NOW.isoformat(),
        "cwd": "/work/fixture",
        "query_head": "fixture query",
        "platform": None,
        "top_scores": [0.75, 0.5],
        "injected": [],
    }
    row.update(overrides)
    return row


def kb_row(*, legacy: bool = False, **overrides: Any) -> dict[str, Any]:
    row = common_row(injected=["doc-1"], cli_status="ok")
    if not legacy:
        row["source"] = "kb"
    row.update(overrides)
    return row


def mem_row(**overrides: Any) -> dict[str, Any]:
    row = common_row(
        injected=[1],
        source="mem",
        session_id="session-fixture",
        channel="claude",
        source_host="claude",
    )
    row.update(overrides)
    row["opportunity_id"] = hashlib.sha256(
        f"{row['channel']}\0{row['session_id']}\0{row['cwd']}\0{row['ts']}".encode(
            "utf-8"
        )
    ).hexdigest()[:20]
    return row


def mem_v0_row(**overrides: Any) -> dict[str, Any]:
    row = common_row(injected=[1], source="mem")
    row.update(overrides)
    return row


def load_script(relative: str) -> dict[str, Any]:
    return runpy.run_path(str(ROOT / relative))


def direct_recall_append_violations(paths: Iterable[Path]) -> list[str]:
    """Find writes whose propagated path expression names recall-log.jsonl."""
    violations: list[str] = []
    allowed = (ROOT / "hooks" / "lib" / "recall_log.py").resolve()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        recall_names: set[str] = set()
        builtin_modules = {"builtins"}
        builtin_open_names = {"open"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "builtins":
                        builtin_modules.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in {"LOG_FILENAME", "RECALL_LOG_FILENAME"}:
                        recall_names.add(alias.asname or alias.name)
                if node.module == "builtins":
                    for alias in node.names:
                        if alias.name == "open":
                            builtin_open_names.add(alias.asname or alias.name)

        def references_recall(node: ast.AST | None) -> bool:
            if node is None:
                return False
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                normalized = node.value.replace("\\", "/")
                return node.value in {
                    recall_log.LOG_FILENAME,
                    "LOG_FILENAME",
                    "RECALL_LOG_FILENAME",
                } or normalized.endswith("/" + recall_log.LOG_FILENAME)
            if isinstance(node, ast.Name):
                return node.id in recall_names
            if isinstance(node, ast.Attribute):
                return node.attr in {
                    "LOG_FILENAME",
                    "RECALL_LOG_FILENAME",
                } or references_recall(node.value)
            return any(references_recall(child) for child in ast.iter_child_nodes(node))

        def assigned_names(target: ast.AST) -> set[str]:
            if isinstance(target, ast.Name):
                return {target.id}
            return {
                name
                for child in ast.iter_child_nodes(target)
                for name in assigned_names(child)
            }

        assignments: list[tuple[list[ast.AST], ast.AST]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                assignments.append((node.targets, node.value))
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                assignments.append(([node.target], node.value))
            elif isinstance(node, ast.NamedExpr):
                assignments.append(([node.target], node.value))
        changed = True
        while changed:
            changed = False
            for targets, value in assignments:
                if not references_recall(value):
                    continue
                for target in targets:
                    for name in assigned_names(target) - recall_names:
                        recall_names.add(name)
                        changed = True

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target: ast.AST | None = None
            mode_index: int | None = None
            method = ""
            if isinstance(node.func, ast.Attribute):
                method = node.func.attr
                if (
                    method == "open"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in builtin_modules
                ):
                    target = node.args[0] if node.args else next(
                        (
                            keyword.value
                            for keyword in node.keywords
                            if keyword.arg == "file"
                        ),
                        None,
                    )
                    mode_index = 1
                elif method in {"open", "write_text", "write_bytes"}:
                    target = node.func.value
                    mode_index = 0 if method == "open" else None
            elif isinstance(node.func, ast.Name) and node.func.id in builtin_open_names:
                method = "open"
                target = node.args[0] if node.args else next(
                    (
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg == "file"
                    ),
                    None,
                )
                mode_index = 1
            if target is None or not references_recall(target):
                continue
            if method in {"write_text", "write_bytes"}:
                destructive = True
            else:
                mode: Any = None
                mode_supplied = False
                if (
                    mode_index is not None
                    and len(node.args) > mode_index
                ):
                    mode_supplied = True
                    if isinstance(node.args[mode_index], ast.Constant):
                        mode = node.args[mode_index].value
                for keyword in node.keywords:
                    if keyword.arg == "mode":
                        mode_supplied = True
                        if isinstance(keyword.value, ast.Constant):
                            mode = keyword.value.value
                destructive = mode_supplied and (
                    not isinstance(mode, str)
                    or any(flag in mode for flag in "awx+")
                )
            if destructive and path.resolve() != allowed:
                violations.append(f"{path}:{node.lineno}")
    return violations


class RecallLogContractTest(unittest.TestCase):
    def test_kb_writer_sets_source_for_all_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            for status in ("ok", "skipped", "timeout", "module_unavailable"):
                self.assertTrue(
                    recall_log.append_kb_recall(
                        home,
                        cwd="/工作/项目",
                        query="查询" * 30,
                        platform="android",
                        top_scores=[0.9],
                        injected=["doc-1"] if status == "ok" else [],
                        cli_status=status,
                        cli_detail="前缀" + "x" * 600,
                    )
                )
            rows = [
                json.loads(line)
                for line in (home / recall_log.LOG_FILENAME)
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual([row["source"] for row in rows], ["kb"] * 4)
            self.assertEqual([row["cli_status"] for row in rows], [
                "ok", "skipped", "timeout", "module_unavailable",
            ])
            self.assertTrue(all(len(row["query_head"]) <= 40 for row in rows))
            self.assertTrue(all(len(row["cli_detail"]) == 500 for row in rows))
            self.assertTrue(all(row["ts"].endswith("+00:00") for row in rows))
            self.assertTrue(all(recall_log.validate_current_recall_record(row) for row in rows))

    def test_mem_writer_preserves_source_and_opportunity_algorithm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            self.assertTrue(
                recall_log.append_mem_recall(
                    home,
                    cwd="/work/fixture",
                    query="remember the stable decision",
                    top_scores=[0.8],
                    injected=[7, 9],
                    session_id="session-1",
                    channel="codex",
                )
            )
            row = json.loads((home / recall_log.LOG_FILENAME).read_text(encoding="utf-8"))
            expected = hashlib.sha256(
                f"codex\0session-1\0/work/fixture\0{row['ts']}".encode("utf-8")
            ).hexdigest()[:20]
            self.assertEqual(row["source"], "mem")
            self.assertEqual(row["source_host"], "codex")
            self.assertEqual(row["opportunity_id"], expected)
            self.assertEqual(recall_log.classify_recall_source(row), "mem")
            self.assertTrue(recall_log.validate_current_recall_record(row))

    def test_writer_contract_errors_are_nonfatal_and_do_not_append(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            self.assertFalse(
                recall_log.append_kb_recall(
                    home,
                    cwd="/work",
                    query="bad score",
                    platform=None,
                    top_scores=[True],
                    injected=[],
                    cli_status="ok",
                )
            )
            self.assertFalse(
                recall_log.append_mem_recall(
                    home,
                    cwd="/work",
                    query="mixed ids",
                    top_scores=[0.8],
                    injected=[1, "2"],
                    session_id="session",
                    channel="claude",
                )
            )
            self.assertFalse((home / recall_log.LOG_FILENAME).exists())

    def test_classifier_strict_current_and_legacy_matrix(self) -> None:
        self.assertEqual(recall_log.classify_recall_source(kb_row()), "kb")
        self.assertEqual(recall_log.classify_recall_source(mem_row()), "mem")
        self.assertEqual(recall_log.classify_recall_source(mem_v0_row()), "mem")
        self.assertEqual(recall_log.classify_recall_source(kb_row(legacy=True)), "kb")
        legacy_without_status = kb_row(legacy=True)
        legacy_without_status.pop("cli_status")
        self.assertEqual(
            recall_log.classify_recall_source(legacy_without_status), "kb"
        )
        self.assertEqual(
            recall_log.classify_recall_source(kb_row(legacy=True, injected=[])),
            "kb",
        )
        explicit_kb_without_status = common_row(source="kb", injected=[])
        self.assertEqual(
            recall_log.classify_recall_source(explicit_kb_without_status), "kb"
        )
        partial_mem = mem_v0_row(session_id="partial")
        forged_mem = mem_row()
        forged_mem["opportunity_id"] = "0" * 20
        self.assertEqual(recall_log.classify_recall_source(partial_mem), "mem")
        self.assertEqual(recall_log.classify_recall_source(forged_mem), "mem")
        self.assertFalse(recall_log.validate_current_recall_record(mem_v0_row()))
        self.assertFalse(
            recall_log.validate_current_recall_record(explicit_kb_without_status)
        )
        self.assertFalse(recall_log.validate_current_recall_record(partial_mem))
        self.assertFalse(recall_log.validate_current_recall_record(forged_mem))
        self.assertIsNone(recall_log.mem_recall_opportunity_key(partial_mem))
        self.assertIsNone(recall_log.mem_recall_opportunity_key(forged_mem))

        invalid_rows = [
            common_row(source=None, injected=[]),
            common_row(source="unknown", injected=[]),
            kb_row(source="mem"),
            mem_v0_row(injected=["1"]),
            kb_row(top_scores=[True]),
            mem_row(injected=[True]),
            mem_row(injected=[1, "2"]),
            common_row(injected=[1]),
            common_row(injected=[], session_id="looks-like-mem"),
            common_row(injected=[], unknown="field"),
        ]
        for row in invalid_rows:
            with self.subTest(row=row):
                self.assertIsNone(recall_log.classify_recall_source(row))

    def test_mixed_historical_fixture_counts_without_mutation(self) -> None:
        status = load_script("scripts/kb/sulde-status.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / recall_log.LOG_FILENAME
            kb = kb_row(legacy=True, injected=[f"doc-{index}" for index in range(48)])
            mem = mem_v0_row(injected=list(range(363)))
            path.write_text(
                json.dumps(kb, ensure_ascii=False) + "\n"
                + json.dumps(mem, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            before = path.read_bytes()
            counts = status["read_recall"](path, NOW)
            after = path.read_bytes()
            self.assertEqual(counts, {
                "recall_today_mem": 363,
                "recall_today_kb": 48,
                "recall_today_unclassified_rows": 0,
            })
            self.assertEqual(after, before)

    def test_status_reports_explicit_mem_with_string_ids_as_unknown(self) -> None:
        status = load_script("scripts/kb/sulde-status.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / recall_log.LOG_FILENAME
            path.write_text(
                json.dumps(common_row(source="mem", injected=["wrong-channel"]))
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(status["read_recall"](path, NOW), {
                "recall_today_mem": 0,
                "recall_today_kb": 0,
                "recall_today_unclassified_rows": 1,
            })

    def test_calibrate_only_consumes_classified_kb(self) -> None:
        calibrate = load_script("scripts/kb/calibrate.py")
        unknown = common_row(injected=[1])
        report = calibrate["analyze"](
            [kb_row(legacy=True), mem_v0_row(), unknown],
            [],
        )
        self.assertEqual(report["recall_count"], 1)
        self.assertEqual(report["injection_count"], 1)

    def test_golden_only_consumes_valid_target_channel(self) -> None:
        golden = load_script("scripts/kb/golden-expand.py")
        malformed_mem = kb_row(source="mem")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / recall_log.LOG_FILENAME
            path.write_text(
                "".join(
                    json.dumps(row) + "\n"
                    for row in (mem_v0_row(), mem_row(), kb_row(), malformed_mem)
                ),
                encoding="utf-8",
            )
            recalls, invalid = golden["read_recalls"](
                path, NOW - timedelta(days=1)
            )
            memory = [row for row in recalls if row.source == "mem"]
            self.assertEqual(len(memory), 2)
            self.assertTrue(all(row.injected == ("1",) for row in memory))
            self.assertEqual(sum(row.source == "kb" for row in recalls), 1)
            self.assertEqual(invalid, 1)

    def test_mem_replay_excludes_kb_and_unknown_rows(self) -> None:
        mem_capture = load_script("hooks/lib/mem_capture.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            with closing(sqlite3.connect(home / "memory.db")) as connection:
                connection.execute(
                    "CREATE TABLE mem_entries(role TEXT, project TEXT, content TEXT, ts TEXT)"
                )
                connection.commit()
            rows = [
                mem_v0_row(injected=[1, 2]),
                kb_row(),
                common_row(injected=[1]),
            ]
            (home / recall_log.LOG_FILENAME).write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            result = mem_capture["replay"](home, NOW + timedelta(hours=1))
            self.assertEqual(result["adopted"], 0)
            self.assertEqual(result["ignored"], 0)
            self.assertEqual(result["unmatched"], 2)

    def test_governance_totals_survive_but_metrics_exclude_unknown(self) -> None:
        governance = load_script("scripts/kb/governance-report.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / recall_log.LOG_FILENAME
            rows = [
                kb_row(),
                mem_v0_row(),
                mem_row(),
                common_row(injected=[999], top_scores=[99.0]),
            ]
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            report = governance["collect_recall"](path, NOW)
            self.assertEqual(report["records_total"], 4)
            self.assertEqual(report["today"]["records_seen"], 4)
            self.assertEqual(report["today"]["recalls"], 3)
            self.assertEqual(report["today"]["unclassified"], 1)
            self.assertEqual(report["today"]["injected"], 3)
            self.assertEqual(report["today"]["score_distribution"]["max"], 0.75)

    def test_governance_adoption_eligibility_requires_valid_mem(self) -> None:
        governance = load_script("scripts/kb/governance-report.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            adoption = home / "adoption.jsonl"
            recalls = home / recall_log.LOG_FILENAME
            adoption.write_text(
                json.dumps({
                    "ts": NOW.isoformat(),
                    "recall_ts": NOW.isoformat(),
                    "session_id": "legacy-session",
                    "entry_id": 1,
                    "verdict": "adopted",
                })
                + "\n",
                encoding="utf-8",
            )
            valid_v1 = mem_row(session_id="v1")
            partial = mem_v0_row(session_id="partial")
            forged = mem_row(session_id="forged")
            forged["opportunity_id"] = "0" * 20
            recalls.write_text(
                "".join(
                    json.dumps(row) + "\n"
                    for row in (
                        mem_v0_row(), valid_v1, kb_row(), partial, forged
                    )
                ),
                encoding="utf-8",
            )
            result = governance["collect_mem_adoption"](
                adoption, NOW, recalls
            )
            self.assertEqual(result["eligible_opportunities_7d"], 2)
            self.assertEqual(result["samples_7d"], 1)
            self.assertEqual(result["adopted_7d"], 1)
            self.assertEqual(result["observation_coverage"], 0.5)

    def test_only_shared_module_can_append_recall_log(self) -> None:
        runtime_paths = [
            path
            # Fixture writers under tests/ are intentionally outside this runtime scan.
            for root in (
                ROOT / "hooks",
                ROOT / "scripts",
                ROOT / "tools",
                ROOT / "integrations",
            )
            for path in root.rglob("*.py")
        ]
        self.assertEqual(direct_recall_append_violations(runtime_paths), [])

        with tempfile.TemporaryDirectory() as temp_dir:
            alias_append = Path(temp_dir) / "alias_append.py"
            alias_append.write_text(
                "from pathlib import Path\n"
                "from builtins import open as opener\n"
                "from recall_log import LOG_FILENAME as recall_name\n"
                "def write(home):\n"
                "    path = Path(home) / recall_name\n"
                "    alias = (target := path)\n"
                "    with opener(alias, 'a', encoding='utf-8') as stream:\n"
                "        stream.write('{}\\n')\n",
                encoding="utf-8",
            )
            overwrite = Path(temp_dir) / "write_text.py"
            overwrite.write_text(
                "from pathlib import Path\n"
                "RECALL_LOG_FILENAME: str = 'recall-log.jsonl'\n"
                "def write(home):\n"
                "    target: Path = Path(home) / RECALL_LOG_FILENAME\n"
                "    alias = target\n"
                "    alias.write_text('{}', encoding='utf-8')\n",
                encoding="utf-8",
            )
            append_findings = direct_recall_append_violations([alias_append])
            overwrite_findings = direct_recall_append_violations([overwrite])
            self.assertEqual(len(append_findings), 1)
            self.assertIn("alias_append.py", append_findings[0])
            self.assertEqual(len(overwrite_findings), 1)
            self.assertIn("write_text.py", overwrite_findings[0])


if __name__ == "__main__":
    unittest.main()
