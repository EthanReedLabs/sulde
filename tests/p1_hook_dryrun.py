#!/usr/bin/env python3
"""sulde P1 hook dry-run test suite.

Spins up a temporary sulde-config'd project under /tmp, feeds JSON payloads
into each hook entrypoint via stdin, and asserts the exit code + stdout
shape match the v2 protocol spec.

Coverage:
  pre_tool_use.py:
    1. Write task-md missing baseline → JSON deny + exit 0
    2. Write task-md with baseline    → no output + exit 0
    3. Write task-md under archive/   → no output + exit 0 (exempt)
    4. Bash `cd <frontend>/`          → stderr + exit 2
    5. Bash absolute path             → no output + exit 0
    6. Bash `git commit` (dev role, no SULDE_COMMIT_ALIAS) → stderr + exit 2
    7. Bash `git as-a commit ...`     → no output + exit 0

  user_prompt_submit.py:
    8. Prompt with skill trigger      → stdout reminder + exit 0
    9. Prompt with perf-gate trigger  → stdout reminder + exit 0
   10. Prompt with no triggers        → intent context + exit 0

  session_start.py:
   11. With CLAUDE.md present         → JSON additionalContext + exit 0

  Cross-cutting:
   12. Non-sulde project (no config)  → silent exit 0
   13. pyyaml ImportError fallback    → stderr warning + exit 0
   14. Legacy codepage override       → UTF-8 prompt survives round-trip
   15. Canon legacy codepage override → UTF-8 JSON survives round-trip
   16. Notify legacy codepage override → UTF-8 JSON survives round-trip

Run:
  python3 tests/p1_hook_dryrun.py
Returns exit 0 on success, 1 on any failure.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


def configure_utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


configure_utf8_stdio()

REPO_ROOT = Path(os.environ.get("SULDE_PLUGIN_UNDER_TEST", Path(__file__).resolve().parents[1]))
HOOKS_DIR = REPO_ROOT / "hooks"
ENTRY_PRE = HOOKS_DIR / "pre_tool_use.py"
ENTRY_PROMPT = HOOKS_DIR / "user_prompt_submit.py"
ENTRY_SESSION = HOOKS_DIR / "session_start.py"
ENTRY_CANON = HOOKS_DIR / "canon_inject.py"
ENTRY_NOTIFICATION = HOOKS_DIR / "notification.py"


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""


# ─── helpers ────────────────────────────────────────────────────────────────

def run_hook(
    entry: Path,
    payload: dict,
    *,
    cwd: Path,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    real_env = os.environ.copy()
    real_env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    if env:
        real_env.update(env)
    return subprocess.run(
        [sys.executable, str(entry)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
        env=real_env,
        timeout=15,
        check=False,
    )


def expect(name: str, cond: bool, detail: str = "") -> Result:
    return Result(name=name, ok=cond, detail=detail)


def write_config(project_root: Path, role: str = "coordinator") -> None:
    (project_root / "android").mkdir(parents=True, exist_ok=True)
    (project_root / "ios").mkdir(parents=True, exist_ok=True)
    cfg = f"""enabled: true
role: {role}
docs_hub: ./docs-hub
frontends:
  - name: android
    path: ./android
    stack: mobile-android
  - name: ios
    path: ./ios
    stack: mobile-ios
enforcement_level: balanced
enforcement_grace_period_days: 7
lang: en
team:
  - alias: as-a
    name: Alice
    email: a@t.com
    frontend: android
"""
    (project_root / ".sulde-config.yaml").write_text(cfg)


# ─── tests ──────────────────────────────────────────────────────────────────

def test_write_task_md_missing_baseline(project: Path) -> Result:
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": f"{project}/android/.ai-workspace/tasks/2026-05-25-foo.md",
            "content": "# foo\n## §1 design\nbar",
        },
    }
    r = run_hook(ENTRY_PRE, payload, cwd=project)
    if r.returncode != 0:
        return expect("write_task_md_missing_baseline", False, f"exit {r.returncode}, stderr={r.stderr[:200]}")
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except json.JSONDecodeError:
        return expect("write_task_md_missing_baseline", False, f"non-JSON stdout: {r.stdout[:200]}")
    decision = out.get("hookSpecificOutput", {}).get("permissionDecision")
    return expect(
        "write_task_md_missing_baseline",
        decision == "deny",
        f"decision={decision}",
    )


def test_write_task_md_with_baseline(project: Path) -> Result:
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": f"{project}/android/.ai-workspace/tasks/2026-05-25-foo.md",
            "content": "---\ncapability_tier: balanced\n---\n# foo\n## §起草前 baseline 实证\n- git log: abc\n## §1\nbar",
        },
    }
    r = run_hook(ENTRY_PRE, payload, cwd=project)
    return expect(
        "write_task_md_with_baseline",
        r.returncode == 0 and not r.stdout.strip(),
        f"exit={r.returncode}, stdout={r.stdout[:120]}",
    )


def test_write_task_md_missing_capability_tier(project: Path) -> Result:
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": f"{project}/android/.ai-workspace/tasks/2026-05-25-no-tier.md",
            "content": "# foo\n## §起草前 baseline 实证\n- git log: abc",
        },
    }
    r = run_hook(ENTRY_PRE, payload, cwd=project)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except json.JSONDecodeError:
        out = {}
    decision = out.get("hookSpecificOutput", {}).get("permissionDecision")
    return expect(
        "write_task_md_missing_capability_tier",
        r.returncode == 0 and decision == "deny" and "capability_tier" in r.stdout,
        f"exit={r.returncode}, decision={decision}, stdout={r.stdout[:160]}",
    )


def test_write_task_md_rejects_provider_model(project: Path) -> Result:
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": f"{project}/android/.ai-workspace/tasks/2026-05-25-provider-model.md",
            "content": "---\nmodel: opus\ncapability_tier: deep\n---\n# foo\n## §起草前 baseline 实证\n- git log: abc",
        },
    }
    r = run_hook(ENTRY_PRE, payload, cwd=project)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except json.JSONDecodeError:
        out = {}
    decision = out.get("hookSpecificOutput", {}).get("permissionDecision")
    return expect(
        "write_task_md_rejects_provider_model",
        r.returncode == 0 and decision == "deny" and "provider-specific" in r.stdout,
        f"exit={r.returncode}, decision={decision}, stdout={r.stdout[:160]}",
    )


def test_write_task_md_allows_business_model_in_body(project: Path) -> Result:
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": f"{project}/android/.ai-workspace/tasks/2026-05-25-business-model.md",
            "content": "---\ncapability_tier: balanced\n---\n# foo\n## §起草前 baseline 实证\n- git log: abc\n## API example\nmodel: ArticleDto",
        },
    }
    r = run_hook(ENTRY_PRE, payload, cwd=project)
    return expect(
        "write_task_md_allows_business_model_in_body",
        r.returncode == 0 and not r.stdout.strip(),
        f"exit={r.returncode}, stdout={r.stdout[:160]}",
    )


def test_write_task_md_archive_exempt(project: Path) -> Result:
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": f"{project}/android/.ai-workspace/tasks/archive/2026-old.md",
            "content": "# old\nfoo",
        },
    }
    r = run_hook(ENTRY_PRE, payload, cwd=project)
    return expect(
        "write_task_md_archive_exempt",
        r.returncode == 0 and not r.stdout.strip(),
        f"exit={r.returncode}, stdout={r.stdout[:120]}",
    )


def test_bash_cd_frontend(project: Path) -> Result:
    payload = {"tool_name": "Bash", "tool_input": {"command": "cd android/ && ls"}}
    r = run_hook(ENTRY_PRE, payload, cwd=project)
    return expect(
        "bash_cd_frontend",
        r.returncode == 2 and "sulde" in r.stderr.lower(),
        f"exit={r.returncode}, stderr_has_sulde={'sulde' in r.stderr.lower()}",
    )


def test_bash_absolute_path(project: Path) -> Result:
    payload = {"tool_name": "Bash", "tool_input": {"command": f"ls {project}/android/"}}
    r = run_hook(ENTRY_PRE, payload, cwd=project)
    return expect(
        "bash_absolute_path",
        r.returncode == 0 and not r.stdout.strip(),
        f"exit={r.returncode}",
    )


def test_bash_git_commit_no_alias(project: Path) -> Result:
    # Need dev role for check_git_commit_alias to fire.
    write_config(project, role="dev")
    payload = {"tool_name": "Bash", "tool_input": {"command": "git commit -m foo"}}
    r = run_hook(ENTRY_PRE, payload, cwd=project)
    write_config(project, role="coordinator")  # restore for later tests
    return expect(
        "bash_git_commit_no_alias",
        r.returncode == 2 and "alias" in r.stderr.lower(),
        f"exit={r.returncode}",
    )


def test_bash_git_as_commit(project: Path) -> Result:
    write_config(project, role="dev")
    payload = {"tool_name": "Bash", "tool_input": {"command": "git as-a commit -m foo"}}
    r = run_hook(ENTRY_PRE, payload, cwd=project)
    write_config(project, role="coordinator")
    return expect(
        "bash_git_as_commit",
        r.returncode == 0,
        f"exit={r.returncode}, stderr={r.stderr[:120]}",
    )


def test_prompt_skill_trigger(project: Path) -> Result:
    payload = {"prompt": "帮我写个 task md 派活给 Dev A"}
    r = run_hook(
        ENTRY_PROMPT,
        payload,
        cwd=project,
        env={"SULDE_KB_HOME": str(project / ".sulde-test-kb")},
    )
    return expect(
        "prompt_skill_trigger",
        r.returncode == 0 and "writing-task-md" in r.stdout,
        f"exit={r.returncode}, stdout has writing-task-md={'writing-task-md' in r.stdout}",
    )


def test_prompt_dispatch_skill_trigger(project: Path) -> Result:
    payload = {"prompt": "签发返修任务，给 Dev 发送继续原任务的档位指令"}
    r = run_hook(ENTRY_PROMPT, payload, cwd=project)
    return expect(
        "prompt_dispatch_skill_trigger",
        r.returncode == 0 and "dispatch-task" in r.stdout,
        f"exit={r.returncode}, stdout has dispatch-task={'dispatch-task' in r.stdout}",
    )


def test_prompt_perf_gate(project: Path) -> Result:
    payload = {"prompt": "app 很卡,帮我优化下"}
    r = run_hook(
        ENTRY_PROMPT,
        payload,
        cwd=project,
        env={"SULDE_KB_HOME": str(project / ".sulde-test-kb")},
    )
    return expect(
        "prompt_perf_gate",
        r.returncode == 0 and ("perf-gate" in r.stdout or "性能" in r.stdout),
        f"exit={r.returncode}, stdout={r.stdout[:120]}",
    )


def test_prompt_no_trigger(project: Path) -> Result:
    payload = {"prompt": "rename a vim register"}
    r = run_hook(
        ENTRY_PROMPT,
        payload,
        cwd=project,
        env={"SULDE_KB_HOME": str(project / ".sulde-test-kb")},
    )
    return expect(
        "prompt_no_trigger",
        r.returncode == 0 and "[sulde intent] ACTIVE" in r.stdout,
        f"exit={r.returncode}, stdout={r.stdout[:120]}",
    )


def test_utf8_protocol_overrides_legacy_codepage(project: Path) -> Result:
    payload = {"prompt": "性能很卡 🙂 请检查"}
    r = run_hook(
        ENTRY_PROMPT,
        payload,
        cwd=project,
        env={
            "PYTHONIOENCODING": "cp936",
            "SULDE_KB_HOME": str(project / ".sulde-test-kb"),
        },
    )
    return expect(
        "utf8_protocol_overrides_legacy_codepage",
        r.returncode == 0 and "性能" in r.stdout,
        f"exit={r.returncode}, stderr={r.stderr[:160]}",
    )


def test_canon_utf8_protocol_overrides_legacy_codepage(project: Path) -> Result:
    try:
        r = run_hook(
            ENTRY_CANON,
            {},
            cwd=project,
            env={"PYTHONIOENCODING": "cp936"},
        )
    except UnicodeDecodeError as exc:
        return expect("canon_utf8_protocol_overrides_legacy_codepage", False, str(exc))
    try:
        output = json.loads(r.stdout)
    except json.JSONDecodeError:
        output = {}
    context = output.get("hookSpecificOutput", {}).get("additionalContext", "")
    return expect(
        "canon_utf8_protocol_overrides_legacy_codepage",
        r.returncode == 0 and "法典" in context,
        f"exit={r.returncode}, stderr={r.stderr[:160]}",
    )


def test_notification_utf8_protocol_overrides_legacy_codepage(project: Path) -> Result:
    with tempfile.TemporaryDirectory(prefix="sulde-notify-boundary-") as td:
        fixture_hooks = Path(td) / "hooks"
        fixture_lib = fixture_hooks / "lib"
        fixture_lib.mkdir(parents=True)
        shutil.copy2(ENTRY_NOTIFICATION, fixture_hooks / "notification.py")
        shutil.copy2(HOOKS_DIR / "lib" / "sulde_common.py", fixture_lib / "sulde_common.py")
        (fixture_lib / "kb_notify.py").write_text(
            "def run(payload):\n"
            "    print('MATCH' if payload.get('message') == '构建完成 🙂' else 'MISMATCH')\n",
            encoding="utf-8",
        )
        try:
            r = run_hook(
                fixture_hooks / "notification.py",
                {"message": "构建完成 🙂"},
                cwd=project,
                env={"PYTHONIOENCODING": "cp936"},
            )
        except UnicodeDecodeError as exc:
            return expect(
                "notification_utf8_protocol_overrides_legacy_codepage", False, str(exc)
            )
    return expect(
        "notification_utf8_protocol_overrides_legacy_codepage",
        r.returncode == 0 and r.stdout.strip() == "MATCH",
        f"exit={r.returncode}, stdout={r.stdout[:120]}, stderr={r.stderr[:160]}",
    )


def test_session_start_with_claude_md(project: Path) -> Result:
    (project / "CLAUDE.md").write_text("# project\n- role: coord\n")
    payload: dict = {}
    r = run_hook(ENTRY_SESSION, payload, cwd=project)
    if r.returncode != 0:
        return expect("session_start_with_claude_md", False, f"exit={r.returncode}")
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except json.JSONDecodeError:
        return expect("session_start_with_claude_md", False, f"non-JSON: {r.stdout[:120]}")
    ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    return expect(
        "session_start_with_claude_md",
        "# project" in ctx,
        f"ctx_has_project={'# project' in ctx}",
    )


def test_non_sulde_project_silent() -> Result:
    with tempfile.TemporaryDirectory(prefix="sulde-nosulde-") as td:
        proj = Path(td)
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(proj / "task.md"), "content": "foo"},
        }
        r = run_hook(ENTRY_PRE, payload, cwd=proj)
        return expect(
            "non_sulde_project_silent",
            r.returncode == 0 and not r.stdout.strip(),
            f"exit={r.returncode}, stdout={r.stdout[:120]}",
        )


def test_pyyaml_importerror_fallback(project: Path) -> Result:
    # Stub yaml.py that raises ImportError to simulate pyyaml absence.
    with tempfile.TemporaryDirectory(prefix="sulde-noyaml-") as stub:
        (Path(stub) / "yaml.py").write_text("raise ImportError('simulated')\n")
        payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        r = run_hook(
            ENTRY_PRE,
            payload,
            cwd=project,
            env={"PYTHONPATH": stub},
        )
        return expect(
            "pyyaml_importerror_fallback",
            r.returncode == 0 and "pyyaml" in r.stderr.lower(),
            f"exit={r.returncode}, stderr_has_pyyaml={'pyyaml' in r.stderr.lower()}",
        )


# ─── runner ─────────────────────────────────────────────────────────────────

def main() -> int:
    if not ENTRY_PRE.exists():
        print(f"FATAL: {ENTRY_PRE} not found — run from a sulde checkout", file=sys.stderr)
        return 1

    results: list[Result] = []
    with tempfile.TemporaryDirectory(prefix="sulde-dryrun-") as td:
        project = Path(td) / "smoke"
        project.mkdir()
        write_config(project)

        results.append(test_write_task_md_missing_baseline(project))
        results.append(test_write_task_md_with_baseline(project))
        results.append(test_write_task_md_missing_capability_tier(project))
        results.append(test_write_task_md_rejects_provider_model(project))
        results.append(test_write_task_md_allows_business_model_in_body(project))
        results.append(test_write_task_md_archive_exempt(project))
        results.append(test_bash_cd_frontend(project))
        results.append(test_bash_absolute_path(project))
        results.append(test_bash_git_commit_no_alias(project))
        results.append(test_bash_git_as_commit(project))
        results.append(test_prompt_skill_trigger(project))
        results.append(test_prompt_dispatch_skill_trigger(project))
        results.append(test_prompt_perf_gate(project))
        results.append(test_prompt_no_trigger(project))
        results.append(test_utf8_protocol_overrides_legacy_codepage(project))
        results.append(test_canon_utf8_protocol_overrides_legacy_codepage(project))
        results.append(test_notification_utf8_protocol_overrides_legacy_codepage(project))
        results.append(test_session_start_with_claude_md(project))
        results.append(test_pyyaml_importerror_fallback(project))

    results.append(test_non_sulde_project_silent())

    passed = sum(1 for r in results if r.ok)
    total = len(results)
    print()
    print(f"sulde P1 hook dry-run: {passed}/{total} passed")
    print()
    for r in results:
        flag = "✅" if r.ok else "❌"
        line = f"  {flag} {r.name}"
        if not r.ok and r.detail:
            line += f"  ({r.detail})"
        print(line)
    print()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
