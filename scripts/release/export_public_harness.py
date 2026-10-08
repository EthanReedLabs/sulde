#!/usr/bin/env python3
"""Build a private, review-only public Harness candidate from frozen Git blobs.

This is intentionally not a publisher or installer. The private report contains
source provenance and must never be copied into the public tree. A successful
export verifies an inventory, not privacy review or release acceptance.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import unicodedata

sys.dont_write_bytecode = True

SCHEMA = "sulde-public-harness-review-v1"
POLICY_VERSION = 6
OVERLAY_PREFIX = "scripts/release/public_harness_overlay/"
OVERLAY_FILES = {
    "README.md": "100644", "knowledge/SEDIMENTATION-STANDARD.md": "100644",
    "hooks/run-hook.sh": "100755", "hooks/run-hook.ps1": "100644",
}
HOOK_SCRIPTS = {
    "pre_tool_use.py", "post_tool_use.py", "user_prompt_submit.py", "canon_inject.py",
    "session_start.py", "pre_compact.py", "notification.py", "stop.py",
}
SOURCE_PREFIXES = (
    ".claude-plugin/", "commands/", "hooks/", "integrations/", "scripts/",
    "skills/", "spec/", "template/", "templates/", "tests/", "tools/",
)
SOURCE_FILES = {
    "CANON.md", "LICENSE-v0.1.0-MIT-archive",
    "docs/dual-runtime-contract.md", "docs/event-observability.md",
    "docs/intent-guardian.md", "docs/kb-retrieval-contract.md",
    "docs/dispatch-task-only.md",
}
PUBLIC_SCAFFOLD_READMES = {
    f"template/{platform}/.ai-workspace/{directory}/README.md"
    for platform in ("android", "flutter", "harmony", "ios")
    for directory in ("baseline", "diag", "handoff", "screenshots", "session-resume", "tasks", "ui-audit")
}
PRIVATE_PARTS = {
    ".git", ".ua", ".sulde", ".worktrees", ".codex-agent", ".ai-workspace",
    ".kb-index", "__pycache__", ".pytest_cache", "node_modules", "venv", ".venv",
    "sessions", "rollouts", "backups", "receipts", "ledgers", "data", "cache",
    "memory", "memories", "session", "rollout", "backup", "ledger", "receipt",
    "production", "logs", "evidence",
}
PRIVATE_SUFFIXES = (
    ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".jsonl", ".jsonl.zst",
    ".zip", ".tar", ".gz", ".zst", ".bak", ".pyc", ".pyo", ".key", ".pem",
)
PRIVATE_FILES = {
    "scripts/community-export-manifest.json",  # Contains private-source pins.
    "scripts/export_community.py", "scripts/export-community.sh",
    "tests/test_export_community.py",
    "scripts/release/export_public_harness.py",  # Private publishing machinery.
    "scripts/release/verify_public_harness_candidate.py",
    "tests/test_export_public_harness.py",
}
TEXT_SUFFIXES = {
    "", ".py", ".sh", ".ps1", ".md", ".json", ".yml", ".yaml", ".toml",
    ".txt", ".template", ".plist", ".cfg", ".tla", ".sample", ".example",
}
WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{index}" for prefix in ("com", "lpt") for index in range(1, 10)
}
REVIEW_PATTERNS = {
    "absolute-user-path": re.compile(r"(?<![A-Za-z0-9_./])/(?:Users|home)/[^/\s\"']+|[A-Za-z]:\\Users\\"),
    "private-repository-name": re.compile(r"sulde-cc-pro|sulde-pro|cognee-project-memory"),
    "business-identity": re.compile(r"Apollo|iquokka|Freebeat|TREVARO", re.I),
    "possible-production-id": re.compile(r"\b(?:att|int)-[0-9a-f]{20,}\b|\b01[0-9a-f]{6}-[0-9a-f-]{27,}\b"),
    "private-key-material": re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    "credential-like-value": re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{24,}|AKIA[A-Z0-9]{16})\b"),
    # A .py suffix does not make embedded operational JSON safe to publish.
    "embedded-operational-record-review": re.compile(r'[\x22\x27]at[\x22\x27]:.*[\x22\x27](?:run_id|workspace_id|session_id)[\x22\x27]:'),
}
PUBLIC_METADATA_FILES = {
    "docs/kb-retrieval-contract.md",
    "integrations/codex/plugins/sulde/.codex-plugin/plugin.json",
    "scripts/kb/calibrate.py", "tests/test_golden_review.py",
    "scripts/kb/install-agents.sh", "scripts/release/stage_plugin.py",
    "templates/launchagents/com.sulde.codex-harvest.plist",
    "tests/test_stage_plugin.py",
}
SYNTHETIC_REPLACEMENT_FILES = {
    "tests/test_intent_guardian.py", "tests/test_session_continuity.py",
    "tests/test_intervention.py", "tests/test_memory_graph_quality.py",
    "tests/test_graph_audit.py", "scripts/kb/graph-audit.py",
    "hooks/lib/check_task_md_baseline.py",
}
SYNTHETIC_REPLACEMENTS = (
    ("019f1d33-e496-7801-bf53-6e213bd12a1f", "00000000-0000-7000-8000-000000000001"),
    ("019feed9-4406-72e2-accf-2e24a01ade69", "00000000-0000-7000-8000-000000000002"),
    ("Apollo", "SyntheticApplication"), ("apollo", "synthetic-application"),
    ("Freebeat", "SyntheticProject"), ("顶尖教练系统", "示例检索系统"),
    ("品牌母题板", "测试样例页面"), ("brand motif board", "test example page"),
)


class ExportError(ValueError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or "\\" in value or ":" in value
            or str(path) != value or unicodedata.normalize("NFC", value) != value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part in {"", ".", ".."} or part.endswith((" ", "."))
                   or part.split(".")[0].casefold() in WINDOWS_RESERVED for part in path.parts)):
        raise ExportError("non-canonical or non-portable repository path")
    return value


def exclusion(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    folded = tuple(part.casefold() for part in parts)
    if path.startswith(OVERLAY_PREFIX):
        return "private-export-overlay-input"
    if folded[0] == "knowledge":
        return "formal-corpus-and-metadata"
    if (folded[0].startswith("guardian-") or folded[0] == "life-program"
            or (folded[0] == "docs" and path not in SOURCE_FILES)):
        return "internal-reports-or-unreviewed-documentation"
    if PRIVATE_PARTS.intersection(folded):
        return "local-state-or-private-history"
    if any(part.startswith(".env") for part in folded) or path in PRIVATE_FILES:
        return "private-configuration-or-export-provenance"
    if path.startswith("tests/fixtures/") or path.lower().endswith(PRIVATE_SUFFIXES):
        return "data-payload-requires-synthetic-replacement"
    return None


def git(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], input=input_bytes,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if result.returncode:
        raise ExportError(f"Git {args[0]} failed (exit {result.returncode}); no source content logged")
    return result.stdout


def snapshot(root: Path, revision: str) -> dict[str, dict]:
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision) is None:
        raise ExportError("use a full immutable commit, not a branch or abbreviated revision")
    if git(root, "rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip() != revision:
        raise ExportError("revision is not an exact commit")
    entries = {}
    portable = set()
    for record in git(root, "ls-tree", "-r", "-z", revision).split(b"\0"):
        if not record:
            continue
        meta, raw_path = record.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        path = safe_path(raw_path.decode("utf-8"))
        if path.casefold() in portable:
            raise ExportError("case-insensitive path collision")
        portable.add(path.casefold())
        entries[path] = {"mode": mode, "kind": kind, "oid": oid}
    return entries


def read_blobs(root: Path, entries: dict[str, dict]) -> dict[str, bytes]:
    for entry in entries.values():
        if entry["kind"] != "blob" or entry["mode"] not in {"100644", "100755"}:
            raise ExportError("selected input is a symlink, submodule or non-regular file")
    paths = sorted(entries)
    if not paths:
        return {}
    # One Git process; data roots and excluded blobs are never opened.
    requested = "".join(entries[path]["oid"] + "\n" for path in paths).encode()
    output = git(root, "cat-file", "--batch", input_bytes=requested)
    cursor = 0
    result = {}
    for path in paths:
        end = output.index(b"\n", cursor)
        oid, kind, size = output[cursor:end].decode().split()
        if oid != entries[path]["oid"] or kind != "blob":
            raise ExportError("Git blob response identity mismatch")
        length = int(size)
        cursor = end + 1
        raw = output[cursor:cursor + length]
        cursor += length
        if len(raw) != length or output[cursor:cursor + 1] != b"\n":
            raise ExportError("truncated Git blob response")
        cursor += 1
        result[path] = raw
    if cursor != len(output):
        raise ExportError("unexpected trailing Git blob response")
    return result


def generated_files(public: dict[str, bytes], source: dict[str, bytes] | None = None) -> dict[str, bytes]:
    empty = {
        "schema_version": 1, "documents": [], "document_count": 0,
        "corpus_sha256": digest(b""),
    }
    generated = {
        "knowledge/MANIFEST.json": encode(empty),
        "knowledge/INDEX.md": (
            "# Knowledge index\n\nThis distribution starts with an empty corpus.\n"
            "No formal knowledge documents or project memory are bundled.\n"
        ).encode(),
        "docs/PUBLIC-DATA-BOUNDARY.md": (
            "# Public data boundary\n\n"
            "The Harness implementation includes Guardian, LIFE, knowledge and memory engines,\n"
            "host adapters, schemas and installation tooling. It does not include any operator's\n"
            "formal corpus, project/session memory, vectors, production ledgers, receipts,\n"
            "internal task reports, credentials or private Git history.\n\n"
            "Runtime state belongs in each user's local data directory. Tests must construct\n"
            "synthetic data. Do not import production exports as test fixtures.\n\n"
            "This is a review candidate, not an accepted release or installation receipt.\n"
        ).encode(),
        ".gitignore": public.get(".gitignore", b"").rstrip() + (
            b"\n\n# Runtime data must remain local\n/.sulde/\n/.ua/\n/.kb-index/\n"
            b"/.codex-agent/\n/.worktrees/\n*.db\n*.db-wal\n*.db-shm\n"
            b"*.sqlite\n*.sqlite3\n*.jsonl\n*.jsonl.zst\n.env*\n"
        ),
    }
    source = source or {}
    descriptor = source.get(".claude-plugin/plugin.json")
    if descriptor:
        version = json.loads(descriptor)["version"]
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.+-]+)?", version):
            raise ExportError("source Claude version is invalid")
        generated["VERSION"] = (version + "\n").encode()
    return generated


def public_hook_manifest(raw: bytes) -> bytes:
    document = json.loads(raw)
    events = document.get("hooks")
    if not isinstance(events, dict) or not events:
        raise ExportError("source Hook inventory is missing")
    for groups in events.values():
        for group in groups:
            for hook in group["hooks"]:
                match = re.fullmatch(r'python3 "\$\{CLAUDE_PLUGIN_ROOT\}/hooks/([a-z_]+\.py)"', hook.get("command", ""))
                if hook.get("type") != "command" or not match or match[1] not in HOOK_SCRIPTS:
                    raise ExportError("unreviewed Hook command; cannot generate a public launcher route")
                hook["command"] = '"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.sh" ' + match[1]
                hook["shell"] = "bash"
    return encode(document)


def public_toolkit_test(raw: bytes) -> bytes:
    # Preserve the old public test and strengthen its inventory expectation:
    # the full Harness has nine handlers over eight events, not three handlers.
    old = '''self.assertEqual(rendered.count('"shell": "bash"'), 3)'''
    new = '''self.assertEqual(rendered.count('"shell": "bash"'), 9)
        self.assertEqual(set(hooks["hooks"]), {
            "PreToolUse", "PostToolUse", "PostToolUseFailure", "UserPromptSubmit",
            "SessionStart", "PreCompact", "Notification", "Stop",
        })'''
    text = raw.decode("utf-8")
    if text.count(old) != 1:
        raise ExportError("public toolkit test drifted; review its Hook inventory before adapting")
    return text.replace(old, new).encode()


def public_machine_metadata(path: str, raw: bytes) -> bytes:
    """Adapt reviewed metadata only; private installation migrations stay private."""
    text = raw.decode("utf-8")
    if path in {"scripts/kb/install-agents.sh", "scripts/release/stage_plugin.py"}:
        # Canonical __SULDE_*__ templates are already supported. The legacy
        # aliases were for a single private installation, not public defaults.
        old_lines = [line for line in text.splitlines(keepends=True)
                     if line.lstrip().startswith('"/Users/eric/')]
        if len(old_lines) != 4:
            raise ExportError("legacy machine mapping drifted; explicit review required")
        for line in old_lines:
            text = text.replace(line, "", 1)
    elif path == "templates/launchagents/com.sulde.codex-harvest.plist":
        old = "/Users/eric/.codex/sessions"
        if text.count(old) != 1:
            raise ExportError("harvest template path drifted")
        text = text.replace(old, "__SULDE_CODEX_SESSIONS__")
    elif path == "tests/test_stage_plugin.py":
        old = 'forbidden = "/Users/eric/ClaudePlugin/sulde-cc-pro"'
        if text.count(old) != 1:
            raise ExportError("staging path regression drifted")
        # Check the current source checkout rather than any developer identity.
        text = text.replace(old, "forbidden = str(ROOT.resolve())")
    elif path == "integrations/codex/plugins/sulde/.codex-plugin/plugin.json":
        try:
            document = json.loads(text)
        except ValueError as error:
            raise ExportError("public repository metadata drifted") from error
        if not isinstance(document, dict):
            raise ExportError("public repository metadata drifted")
        approved_urls = {
            "https://github.com/EthanReedLabs/sulde-cc-pro",
            "https://github.com/EthanReedLabs/sulde-pro",
        }
        for field in ("homepage", "repository"):
            if document.get(field) not in approved_urls:
                raise ExportError("public repository metadata drifted")
            document[field] = "https://github.com/EthanReedLabs/sulde-cc"
        text = encode(document).decode("utf-8")
    else:
        if "sulde-cc-pro" not in text:
            raise ExportError("public repository metadata drifted")
        text = text.replace("sulde-cc-pro", "sulde-cc")
    if "/Users/eric/" in text or "sulde-cc-pro" in text or "sulde-pro" in text:
        raise ExportError("unreviewed private machine metadata remains")
    return text.encode()


def public_composition_test(raw: bytes) -> bytes:
    """Keep executable integration coverage, not a private release's report audit."""
    text = raw.decode("utf-8")
    module = ast.parse(text)
    assignments = [node for node in module.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "COMPOSITION_CASES"
                           for target in node.targets)]
    if len(assignments) != 1:
        raise ExportError("composition inventory drifted")
    cases = ast.literal_eval(assignments[0].value)
    if (not isinstance(cases, tuple) or len(cases) != 16 or len(set(cases)) != 16
            or any(not isinstance(case, str) or not re.fullmatch(r"tests\.test_\w+\.\w+\.test_\w+", case)
                   for case in cases)):
        raise ExportError("unreviewed composition test inventory")
    # The two private fixture/report-audit tests are not runtime tests and are
    # deliberately not copied or counted as passed. The sixteen real component
    # tests are loaded and executed unchanged, with zero skips/errors required.
    return (
        '"""Data-free composition regression; not private historical acceptance."""\n'
        'import unittest\n\nCOMPOSITION_CASES = ' + repr(cases) + '\n\n'
        'class PublicGuardianCompositionTests(unittest.TestCase):\n'
        '    def test_public_boundaries_compose_without_skips_or_errors(self):\n'
        '        suite = unittest.defaultTestLoader.loadTestsFromNames(COMPOSITION_CASES)\n'
        '        result = unittest.TestResult()\n'
        '        suite.run(result)\n'
        '        self.assertEqual(result.testsRun, len(COMPOSITION_CASES))\n'
        '        self.assertEqual(result.failures, [])\n'
        '        self.assertEqual(result.errors, [])\n'
        '        self.assertEqual(result.skipped, [])\n'
    ).encode()


def public_operator_state(path: str, raw: bytes) -> bytes:
    """Do not ship a private operator's decisions, goals or initialized identity."""
    text = raw.decode("utf-8")
    if path == "scripts/kb/governance-report.py":
        assignments = [node for node in ast.parse(text).body if isinstance(node, ast.Assign)
                       and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                       and node.targets[0].id == "DECISION_TRACE"]
        if len(assignments) != 1 or not isinstance(ast.literal_eval(assignments[0].value), str):
            raise ExportError("operator decision trace inventory drifted")
        node = assignments[0]
        lines = text.splitlines(keepends=True)
        lines[node.lineno - 1:node.end_lineno] = [
            'DECISION_TRACE = "本分发不包含历史提案处置记录；结论与批准状态须以本地可核验记录为准"\n']
        return "".join(lines).encode()
    if path != "templates/SELF.md":
        raise ExportError("unknown operator state projection")
    for before, after in (
        ("我是 sulde，eric 的工程记忆与知识生命体。", "我是 sulde，当前使用者的工程记忆与知识助手。"),
        ("## 我是什么(2026-08-09 定稿)", "## 我是什么"),
        ("| 级 | 能力 | 我的现状 |", "| 级 | 能力 | 本地验收状态 |"),
    ):
        if text.count(before) != 1:
            raise ExportError("operator identity template drifted")
        text = text.replace(before, after, 1)
    text, count = re.subn(r"(?m)^(\| L[1-4] [^|]+\|[^|]+\|)[^\n]+$",
                         r"\1 未初始化；以本地验收记录为准 |", text)
    if count != 4:
        raise ExportError("operator capability table drifted")
    if text.count("## 目标栈\n") != 1 or text.count("## 观察清单\n") != 1:
        raise ExportError("operator goals inventory drifted")
    start, end = text.index("## 目标栈\n"), text.index("## 观察清单\n")
    if end <= start:
        raise ExportError("operator goal section order drifted")
    text = (text[:start] + "## 目标栈\n\n_空；由本地使用者确认目标后建立，不继承任何发布者任务或权限。_\n\n"
            + text[end:])
    return text.encode()


def public_runtime_fixture(raw: bytes) -> bytes:
    """Generate interruption records from schema, not sanitized production rows."""
    text = raw.decode("utf-8")
    module = ast.parse(text)
    assignments = {node.targets[0].id: node for node in module.body
                   if isinstance(node, ast.Assign) and len(node.targets) == 1
                   and isinstance(node.targets[0], ast.Name)}
    expected = {"H06H_RUN_LEDGER", "H06H_EVENTS_SUMMARY"}
    if not expected <= assignments.keys():
        raise ExportError("runtime regression fixture shape drifted")
    old_ledger = ast.literal_eval(assignments["H06H_RUN_LEDGER"].value)
    if not isinstance(old_ledger, bytes) or old_ledger.count(b"\n") != 5:
        raise ExportError("runtime regression ledger inventory drifted")
    run_id = "run-" + "1" * 24
    common = {"schema": "sulde-run-event-v1", "provider": "codex", "run_id": run_id}
    # These are independently authored synthetic inputs to the real parser.
    events = [
        {"type": "execution.requested", "parent_death_watchdog": True,
         "command_sha256": digest(b"synthetic-command"),
         "execution_binding_sha256": digest(b"synthetic-binding"),
         "workspace_id": "sha256:" + digest(b"synthetic-workspace")[:24]},
        {"type": "execution.started", "parent_death_watchdog": True,
         "pid": 4242, "tree_scope": "posix-process-group"},
        {"type": "execution.interrupt_requested", "reason": "external_effect_outcome_unknown"},
        {"type": "execution.result", "output_present": False, "output_sha256": None,
         "returncode": 0, "stop_reason": "awaiting_human"},
        {"type": "execution.disposed", "error_count": 0, "errors_sha256": None,
         "quiescent": True, "tree_scope": "posix-process-group"},
    ]
    ledger = b"".join((json.dumps({**common, **event, "at": f"2000-01-01T00:00:0{index}+00:00"},
                                sort_keys=True) + "\n").encode()
                      for index, event in enumerate(events))
    stream = b"".join((json.dumps({"type": "synthetic.progress", "step": index}) + "\n").encode()
                       for index in range(48))
    summary = {"line_count": 48, "valid_json_line_count": 48, "sha256": digest(stream),
               "terminal_event": "none", "terminal_event_count": 0}
    for name, value in (("H06H_RUN_LEDGER", ledger), ("H06H_EVENTS_SUMMARY", summary)):
        segment = ast.get_source_segment(text, assignments[name])
        if not segment or text.count(segment) != 1:
            raise ExportError("runtime fixture source identity is ambiguous")
        # Replace later source segments first: AST offsets refer to original text.
    spans = [(assignments[name].lineno, assignments[name].end_lineno, name + " = " + repr(value) + "\n")
             for name, value in (("H06H_RUN_LEDGER", ledger), ("H06H_EVENTS_SUMMARY", summary))]
    lines = text.splitlines(keepends=True)
    for start, end, replacement in sorted(spans, reverse=True):
        lines[start - 1:end] = [replacement]
    text = "".join(lines)
    for before, after in (
        (f"self.assertEqual(len(H06H_RUN_LEDGER), {len(old_ledger)})",
         f"self.assertEqual(len(H06H_RUN_LEDGER), {len(ledger)})"),
        (digest(old_ledger), digest(ledger)),
        ("run-1c18f868428c471e959e751a", run_id),
        ('"provider_pid": 26837', '"provider_pid": 4242'),
        ("2026-08-27T13:25:31Z", "2000-01-01T00:00:00Z"),
        ("2026-08-27T13:29:30Z", "2000-01-01T00:00:04Z"),
        ("test_frozen_h06h_bytes_runtime_to_production_broker_round_trip",
         "test_synthetic_interruption_runtime_to_production_broker_round_trip"),
    ):
        if before not in text:
            raise ExportError("runtime fixture consumer drifted; review required")
        text = text.replace(before, after)
    return public_runtime_task_fixture(text.encode())


def public_runtime_task_fixture(raw: bytes) -> bytes:
    """Keep schema/authority tests, not an actual private task or clone recipe."""
    text = raw.decode("utf-8")
    module = ast.parse(text)
    assignments = {node.targets[0].id: node for node in module.body
                   if isinstance(node, ast.Assign) and len(node.targets) == 1
                   and isinstance(node.targets[0], ast.Name)}
    expected = {"REPAIR6_BRIEF_SHA256", "CURRENT_BASE_COMMIT", "HISTORICAL_T04_TASK_V1"}
    helpers = [node for node in module.body if isinstance(node, ast.FunctionDef)
               and node.name == "run_h06i_fresh_clone_gate"]
    if not expected <= assignments.keys() or len(helpers) != 1:
        raise ExportError("private runtime task fixture inventory drifted")
    if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
           and node.func.id == helpers[0].name for node in ast.walk(module)):
        raise ExportError("private clone helper acquired a consumer; review required")
    # Independently constructed schema inputs. No field is taken from the old
    # task, and the private Git objects / brief are not needed to execute them.
    legacy = {
        "schema": "sulde-guardian-program-task-v1",
        "task_id": "synthetic-legacy-task", "title": "Synthetic legacy schema boundary",
        "owner": "synthetic-worker", "capability_tier": "deep",
        "base_commit": "1" * 40, "depends_on": [], "supersedes": [],
        "owned_paths": ["scripts/kb/agent-runtime.py", "tests/test_agent_runtime.py"],
        "requirements": [],
        "acceptance": ["Reject a mismatched base binding", "Preserve exact owned paths"],
        "evidence_gates": {
            "implemented": ["task_report", "changed_files"],
            "task_verified": ["targeted_tests", "failure_injection"],
            "integrated": ["integration_tests"], "system_verified": ["system_tests"],
        },
    }
    replacements = {
        "REPAIR6_BRIEF_SHA256": digest(b"independent synthetic current brief"),
        "CURRENT_BASE_COMMIT": "2" * 40,
        "HISTORICAL_T04_TASK_V1": legacy,
    }
    spans = [(assignments[name].lineno, assignments[name].end_lineno,
              name + " = " + repr(value) + "\n") for name, value in replacements.items()]
    spans.append((helpers[0].lineno, helpers[0].end_lineno,
                  "# Private release clone audit is retained only in the private source.\n"))
    lines = text.splitlines(keepends=True)
    for start, end, replacement in sorted(spans, reverse=True):
        lines[start - 1:end] = [replacement]
    text = "".join(lines)
    for before, after in (
        ("HISTORICAL_T04_TASK_V1", "SYNTHETIC_LEGACY_TASK_V1"),
        ("CURRENT_BASE_COMMIT", "SYNTHETIC_CURRENT_BASE_COMMIT"),
        ("REPAIR6_BRIEF_SHA256", "SYNTHETIC_BRIEF_SHA256"),
        ("T04-audit-isolation", "synthetic-legacy-task"),
        ("T23-runtime-host-parity-r121-repair2", "synthetic-current-brief"),
        ("T23-runtime-host-parity-r121", "synthetic-current-task"),
        ("test_historical_t04_schema_is_separate_from_current_execution_authority",
         "test_synthetic_legacy_schema_is_separate_from_current_execution_authority"),
    ):
        if before not in text:
            raise ExportError("runtime task fixture consumer drifted; review required")
        text = text.replace(before, after)
    return text.encode()


def review_content(path: str, raw: bytes) -> list[dict]:
    if b"\0" in raw:
        return [{"path": path, "kind": "binary-content", "line": 0}]
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        return [{"path": path, "kind": "non-UTF8-content", "line": 0}]
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        for kind, pattern in REVIEW_PATTERNS.items():
            if pattern.search(line):
                findings.append({"path": path, "kind": kind, "line": number})
    return findings


def build_plan(source: Path, source_revision: str, public: Path,
               public_revision: str) -> tuple[dict, dict[str, bytes]]:
    inventories = {
        "source": snapshot(source, source_revision),
        "public": snapshot(public, public_revision),
    }
    selected = {"source": {}, "public": {}}
    excluded = []
    for origin, entries in inventories.items():
        for path, entry in sorted(entries.items()):
            reason = exclusion(path)
            if origin == "public" and path.startswith("docs/") and reason == "internal-reports-or-unreviewed-documentation":
                reason = None  # Already-public guides are not private reports.
            if origin == "public" and path in PUBLIC_SCAFFOLD_READMES:
                # Preserve only the existing public scaffold instructions. The
                # same paths from private source, and all real task files, stay
                # excluded; a directory name alone cannot distinguish the two.
                reason = None
            if origin == "source" and not reason and not (
                path in SOURCE_FILES or path.startswith(SOURCE_PREFIXES)
            ):
                reason = "not-in-source-code-allowlist"
            if reason:
                excluded.append({"origin": origin, "path": path, "reason": reason})
                continue
            if PurePosixPath(path).suffix not in TEXT_SUFFIXES and not path.startswith("LICENSE"):
                raise ExportError(f"unreviewed source format: {path}")
            selected[origin][path] = entry
    if "LICENSE" not in selected["public"]:
        raise ExportError("public LICENSE must exist and remain unchanged")
    blobs = {
        "source": read_blobs(source, selected["source"]),
        "public": read_blobs(public, selected["public"]),
    }
    payload = dict(blobs["public"])
    payload.update(blobs["source"])
    generated = generated_files(blobs["public"], blobs["source"])
    transformations = []
    runtime_fixture = "tests/test_agent_runtime.py"
    if runtime_fixture in payload:
        original = payload[runtime_fixture]
        rendered = public_runtime_fixture(original)
        generated[runtime_fixture] = rendered
        transformations.append({"path": runtime_fixture, "kind": "independently-constructed-runtime-fixtures",
                                "input_sha256": digest(original), "output_sha256": digest(rendered),
                                "synthetic_event_count": 5, "synthetic_legacy_task_count": 1,
                                "private_clone_helper_not_published": True})
    composition = "tests/test_r2_guardian_integration.py"
    if composition in payload:
        original = payload[composition]
        rendered = public_composition_test(original)
        generated[composition] = rendered
        transformations.append({"path": composition, "kind": "private-report-audit-separated-from-runtime-regression",
                                "input_sha256": digest(original), "output_sha256": digest(rendered),
                                "private_historical_assertions_not_published": 2,
                                "runtime_composition_cases_retained": 16})
    for path in sorted(PUBLIC_METADATA_FILES & payload.keys()):
        original = payload[path]
        rendered = public_machine_metadata(path, original)
        generated[path] = rendered
        transformations.append({"path": path, "kind": "public-machine-metadata",
                                "input_sha256": digest(original), "output_sha256": digest(rendered)})
    for path in ("scripts/kb/governance-report.py", "templates/SELF.md"):
        if path in payload:
            original = payload[path]
            rendered = public_operator_state(path, original)
            generated[path] = rendered
            transformations.append({"path": path, "kind": "operator-state-not-inherited",
                                    "input_sha256": digest(original), "output_sha256": digest(rendered)})
    for path in sorted(SYNTHETIC_REPLACEMENT_FILES & payload.keys()):
        original = payload[path]
        rendered = original.decode("utf-8")
        for before, after in SYNTHETIC_REPLACEMENTS:
            rendered = rendered.replace(before, after)
        if rendered.encode() != original:
            generated[path] = rendered.encode()
            transformations.append({"path": path, "kind": "synthetic-example-identity",
                                    "input_sha256": digest(original), "output_sha256": digest(rendered.encode())})
    overlay_entries = {path: entry for path, entry in inventories["source"].items()
                       if path.startswith(OVERLAY_PREFIX)}
    overlay = {}
    if overlay_entries:
        if set(overlay_entries) != {OVERLAY_PREFIX + path for path in OVERLAY_FILES}:
            raise ExportError("public overlay inventory does not match the explicit allowlist")
        overlay = read_blobs(source, overlay_entries)
        generated.update({path.removeprefix(OVERLAY_PREFIX): raw for path, raw in overlay.items()})
        generated["hooks/hooks.json"] = public_hook_manifest(blobs["source"]["hooks/hooks.json"])
        if "tests/test_public_toolkit.py" in blobs["public"]:
            generated["tests/test_public_toolkit.py"] = public_toolkit_test(blobs["public"]["tests/test_public_toolkit.py"])
    payload.update(generated)
    files = []
    findings = []
    portable = set()
    for path, raw in sorted(payload.items()):
        safe_path(path)
        if path.casefold() in portable:
            raise ExportError("cross-repository case-insensitive collision")
        portable.add(path.casefold())
        origin = "generated" if path in generated else (
            "source" if path in blobs["source"] else "public")
        if origin == "generated":
            prior = selected["source"].get(path) or selected["public"].get(path) or {}
            mode = OVERLAY_FILES.get(path, prior.get("mode", "100644"))
        else:
            mode = selected[origin][path]["mode"]
        files.append({"path": path, "origin": origin, "mode": mode, "sha256": digest(raw),
                      "bytes": len(raw), "replaces_public": (
                          path in blobs["public"] and raw != blobs["public"][path])})
        findings.extend(review_content(path, raw))
    # A missing private fixture or instruction must be reviewed, not disguised
    # as a passing test or replaced by a copied production payload.
    missing = {
        "knowledge/SEDIMENTATION-STANDARD.md": "sediment-rule-needs-data-free-public-version",
        "tests/fixtures/guardian-production-ledger-sanitized.jsonl": "synthetic-ledger-fixture-required",
        "tests/fixtures/r2-guardian-incidents/replay-cases.json": "synthetic-replay-fixture-required",
    }
    for path, reason in missing.items():
        referenced = any(PurePosixPath(path).name.encode() in raw for raw in payload.values())
        if path in inventories["source"] and path not in payload and referenced:
            findings.append({"path": path, "kind": reason, "line": 0})
    plan = {
        "schema": SCHEMA, "policy_version": POLICY_VERSION,
        "source_revision": source_revision, "public_revision": public_revision,
        "generator_sha256": digest(Path(__file__).read_bytes()),
        "overlay_inputs": {path: digest(raw) for path, raw in sorted(overlay.items())},
        "transformations": transformations,
        "release_ready": False, "review_only": True,
        "files": files, "excluded": excluded, "findings": findings,
        "required_gates": ["privacy-and-instruction-review", "public-cli-compatibility",
                           "synthetic-fixture-replacement", "isolated-source-tests",
                           "empty-data-bootstrap-and-mcp", "dual-host-artifacts",
                           "exact-publication-approval"],
    }
    plan["manifest_sha256"] = digest(encode(plan))
    return plan, payload


def checked_new_directory(path: Path) -> Path:
    absolute = path.absolute()
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise ExportError("output path contains a symlink")
    if absolute.exists():
        raise ExportError("output must not exist; never overwrite a previous candidate")
    absolute.mkdir(mode=0o700, parents=True)
    return absolute


def verify_tree(root: Path, plan: dict) -> None:
    frozen = dict(plan)
    expected_digest = frozen.pop("manifest_sha256", None)
    if digest(encode(frozen)) != expected_digest:
        raise ExportError("review manifest digest mismatch")
    expected = {entry["path"]: entry for entry in plan["files"]}
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ExportError("candidate contains a symlink")
        metadata = path.stat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ExportError("candidate contains a non-regular file")
        relative = path.relative_to(root).as_posix()
        actual.add(relative)
        entry = expected.get(relative)
        if entry is None or digest(path.read_bytes()) != entry["sha256"]:
            raise ExportError(f"candidate inventory/content mismatch: {relative}")
        if os.name != "nt" and stat.S_IMODE(metadata.st_mode) != int(entry["mode"], 8) & 0o777:
            raise ExportError(f"candidate mode mismatch: {relative}")
    if actual != set(expected):
        raise ExportError("candidate inventory has missing files")
    manifest = json.loads((root / "knowledge/MANIFEST.json").read_bytes())
    if manifest != {"schema_version": 1, "documents": [], "document_count": 0,
                    "corpus_sha256": digest(b"")}:
        raise ExportError("candidate contains nonempty or invalid formal corpus metadata")
    allowed_knowledge = {"knowledge/MANIFEST.json", "knowledge/INDEX.md"}
    if OVERLAY_PREFIX + "knowledge/SEDIMENTATION-STANDARD.md" in plan.get("overlay_inputs", {}):
        allowed_knowledge.add("knowledge/SEDIMENTATION-STANDARD.md")
    if {path for path in actual if path.startswith("knowledge/")} != allowed_knowledge:
        raise ExportError("candidate contains unexpected formal knowledge files")


def stage_review(output: Path, plan: dict, payload: dict[str, bytes]) -> None:
    # Freeze content and paths BEFORE creating anything. No public target or
    # existing directory can be changed by this entry point.
    frozen = dict(plan)
    if frozen.pop("manifest_sha256", None) != digest(encode(frozen)):
        raise ExportError("review manifest digest mismatch")
    if len(plan["files"]) != len(payload) or {item["path"] for item in plan["files"]} != set(payload):
        raise ExportError("payload inventory changed after planning")
    for entry in plan["files"]:
        safe_path(entry["path"])
        if entry["mode"] not in {"100644", "100755"}:
            raise ExportError("invalid payload mode")
        if digest(payload[entry["path"]]) != entry["sha256"]:
            raise ExportError("payload digest changed after planning")
    output = checked_new_directory(output)
    tree = output / "tree"
    tree.mkdir(mode=0o700)
    # Interrupted staging remains explicitly unaccepted and recoverable.
    (output / "INCOMPLETE").write_text("Unaccepted private export candidate.\n", encoding="utf-8")
    for entry in plan["files"]:
        target = tree / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(payload[entry["path"]])
        target.chmod(int(entry["mode"], 8) & 0o777)
    verify_tree(tree, plan)
    with (output / "review.json").open("xb") as handle:
        handle.write(encode(plan))
    (output / "review.json").chmod(0o600)
    (output / "INCOMPLETE").rename(output / "REVIEW_ONLY")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--public-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan, payload = build_plan(args.source, args.source_revision, args.public, args.public_revision)
        stage_review(args.output, plan, payload)
    except (ExportError, OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        print(f"public export failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "review_only", "release_ready": False,
                      "files": len(plan["files"]), "excluded": len(plan["excluded"]),
                      "findings": dict(Counter(item["kind"] for item in plan["findings"])),
                      "manifest_sha256": plan["manifest_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
