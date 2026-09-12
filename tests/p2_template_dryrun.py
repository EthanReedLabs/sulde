#!/usr/bin/env python3
"""sulde-cc P2 template dry-run test suite.

Validates the v0.2.0 template/ tree by:
  1. Asserting each expected file exists in template/_project/ and
     template/{android,ios,flutter,harmony}/.
  2. Asserting executable bit on scripts that need it.
  3. Asserting CLAUDE.md.template files mention the expected stack-specific
     commands per V0.2.0-DESIGN-v2.md §7.2.
  4. Simulating /sulde-init by shutil.copytree'ing _project/ + one stack to
     a /tmp scratch project and verifying the resulting layout.

Run:
  python3 tests/p2_template_dryrun.py
Returns 0 on success, 1 on any failure.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parent.parent
REPO = Path(os.environ.get("SULDE_PLUGIN_UNDER_TEST", CHECKOUT)).expanduser().resolve()
TEMPLATE = REPO / "template"

EXECUTABLE_PATHS = (
    Path("scripts/kb/bootstrap.sh"),
    Path("scripts/kb/kb-index"),
    Path("integrations/codex/plugins/sulde/scripts/run-hook.sh"),
    Path("template/_project/scripts/coordinator-baseline.sh.template"),
    Path("template/_project/scripts/health-check.sh.template"),
    Path("template/android/scripts/pre-commit-installer.sh"),
    Path("template/ios/scripts/pre-commit-installer.sh"),
    Path("template/flutter/scripts/pre-commit-installer.sh"),
    Path("template/harmony/scripts/pre-commit-installer.sh"),
)

PYTHON_EXECUTABLE_PATHS = (Path("scripts/kb/kb-index"),)

STACKS = ("android", "ios", "flutter", "harmony")
AI_WORKSPACE_SUBDIRS = (
    "tasks", "handoff", "baseline", "session-resume",
    "diag", "screenshots", "ui-audit",
)

# Stack-specific command sentinels — verifies CLAUDE.md.template is real,
# not just the android one copied. Pulled from V0.2.0-DESIGN-v2.md §7.2.
STACK_COMMAND_SIGNATURES = {
    "android": ("./gradlew", "adb install", "adb logcat"),
    "ios":     ("xcodebuild", "ios-deploy", "idevicesyslog"),
    "flutter": ("flutter build apk", "flutter install", "flutter logs"),
    "harmony": ("hvigorw assembleHap", "hdc install", "hdc shell hilog"),
}


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""


def expect(name: str, cond: bool, detail: str = "") -> Result:
    return Result(name=name, ok=cond, detail=detail)


# ─── tests ──────────────────────────────────────────────────────────────────

def test_project_root_files() -> list[Result]:
    expected = [
        "_project/README.md",
        "_project/.gitignore.template",
        "_project/.sulde-config.yaml.example",
        "_project/scripts/README.md",
        "_project/scripts/coordinator-baseline.sh.template",
        "_project/scripts/health-check.sh.template",
        "_project/docs-hub/README.md",
        "_project/docs-hub/coordinator-todos.md.template",
        "_project/docs-hub/00_shared-rules/README.md",
        "_project/docs-hub/design-truth/README.md",
        "_project/docs-hub/design-truth/_example.md.template",
        "_project/docs-hub/ADR/INDEX.md",
        "_project/docs-hub/ADR/_frontmatter.schema.yaml",
        "_project/docs-hub/ADR/0000-example.md",
    ]
    return [
        expect(f"_project_file:{p}", (TEMPLATE / p).exists())
        for p in expected
    ]


def test_stack_files() -> list[Result]:
    results: list[Result] = []
    for stack in STACKS:
        base = TEMPLATE / stack
        expected = [
            "CLAUDE.md.template",
            ".gitignore.template",
            "README.md",
            "scripts/pre-commit-installer.sh",
        ]
        for p in expected:
            results.append(expect(f"{stack}_file:{p}", (base / p).exists()))
        for sub in AI_WORKSPACE_SUBDIRS:
            results.append(expect(
                f"{stack}_aiws:{sub}/README.md",
                (base / ".ai-workspace" / sub / "README.md").exists(),
            ))
    return results


def git_index_modes() -> tuple[dict[str, str], str]:
    try:
        output = subprocess.check_output(
            [
                "git",
                "ls-files",
                "-s",
                "--",
                *[path.as_posix() for path in EXECUTABLE_PATHS],
            ],
            cwd=CHECKOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return {}, str(exc)

    modes: dict[str, str] = {}
    for line in output.splitlines():
        metadata, path = line.split("\t", 1)
        modes[path] = metadata.split(" ", 1)[0]
    return modes, ""


def find_git_bash() -> Path | None:
    git = shutil.which("git")
    candidates: list[Path] = []
    if git:
        git_root = Path(git).resolve().parent.parent
        candidates.extend((git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe"))
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(variable)
        if root:
            candidates.extend(
                (Path(root) / "Git" / "bin" / "bash.exe", Path(root) / "Git" / "usr" / "bin" / "bash.exe")
            )
    discovered = shutil.which("bash.exe") or shutil.which("bash")
    if discovered and "git" in {part.casefold() for part in Path(discovered).parts}:
        candidates.append(Path(discovered))
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def bash_syntax(relative: Path, bash: Path | None) -> tuple[bool, str]:
    if bash is None:
        return False, "Git Bash not found"

    source = CHECKOUT / relative
    with tempfile.TemporaryDirectory(prefix="sulde-p2-bash-") as temp_dir:
        target = source
        if source.suffix == ".template":
            target = Path(temp_dir) / source.name.removesuffix(".template")
            rendered = source.read_text(encoding="utf-8")
            rendered = rendered.replace("<<FRONTENDS>>", '"android" "ios"')
            rendered = rendered.replace("<<DOCS_HUB>>", "docs-hub")
            target.write_text(rendered, encoding="utf-8")
        completed = subprocess.run(
            [str(bash), "-n", target.as_posix()],
            cwd=CHECKOUT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return completed.returncode == 0, completed.stderr.strip()


def python_syntax(relative: Path) -> tuple[bool, str]:
    source = (CHECKOUT / relative).read_bytes()
    if not source.startswith(b"#!/usr/bin/env python3\n"):
        return False, "missing Python shebang"
    try:
        compile(source, str(relative), "exec")
    except SyntaxError as error:
        return False, str(error)
    return True, ""


def test_executable_contract() -> list[Result]:
    results: list[Result] = []
    modes, git_error = git_index_modes()
    for relative in EXECUTABLE_PATHS:
        rendered = relative.as_posix()
        actual = modes.get(rendered)
        results.append(expect(
            f"git_exec_mode:{rendered}",
            actual == "100755",
            git_error or f"mode={actual or 'missing'}",
        ))

    if os.name != "nt":
        for relative in EXECUTABLE_PATHS:
            target = CHECKOUT / relative
            mode = target.stat().st_mode if target.exists() else 0
            results.append(expect(
                f"posix_exec_bit:{relative.as_posix()}",
                bool(mode & 0o111),
                f"mode={oct(mode)}" if target.exists() else f"missing: {target}",
            ))
    else:
        bash = find_git_bash()
        for relative in EXECUTABLE_PATHS:
            if relative in PYTHON_EXECUTABLE_PATHS:
                ok, detail = python_syntax(relative)
                syntax = "python_syntax"
            else:
                ok, detail = bash_syntax(relative, bash)
                syntax = "bash_syntax"
            results.append(expect(
                f"{syntax}:{relative.as_posix()}",
                ok,
                detail,
            ))
    return results


def test_stack_command_signatures() -> list[Result]:
    results: list[Result] = []
    for stack, sentinels in STACK_COMMAND_SIGNATURES.items():
        claude_md = TEMPLATE / stack / "CLAUDE.md.template"
        if not claude_md.exists():
            results.append(expect(f"{stack}_signature", False, "CLAUDE.md.template missing"))
            continue
        content = claude_md.read_text(encoding="utf-8")
        missing = [s for s in sentinels if s not in content]
        results.append(expect(
            f"{stack}_signature",
            not missing,
            f"missing sentinels: {missing}" if missing else "",
        ))
    return results


def test_no_residual_frontend_a() -> list[Result]:
    return [expect(
        "no_frontend_a_residual",
        not (TEMPLATE / "frontend-a").exists(),
        "template/frontend-a/ still present (v0.1.0 placeholder)",
    )]


def test_copytree_simulation() -> list[Result]:
    """Simulate /sulde-init copying _project/ + one stack into a tmp project."""
    results: list[Result] = []
    with tempfile.TemporaryDirectory(prefix="sulde-p2-cp-") as td:
        proj = Path(td)
        # Copy _project/* into project root
        for item in (TEMPLATE / "_project").iterdir():
            target = proj / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
        # Copy template/harmony/ → project/harmony/
        shutil.copytree(TEMPLATE / "harmony", proj / "harmony")

        # Re-apply exec bit on scripts (Windows-safe pattern from configure-sulde §9)
        for sh in proj.glob("**/*.sh"):
            sh.chmod(sh.stat().st_mode | 0o755)
        for sh in proj.glob("**/*.sh.template"):
            sh.chmod(sh.stat().st_mode | 0o755)

        # Assert the result looks right
        results.append(expect(
            "cp:project_readme",
            (proj / "README.md").exists(),
        ))
        results.append(expect(
            "cp:gitignore_template",
            (proj / ".gitignore.template").exists(),
        ))
        results.append(expect(
            "cp:config_example",
            (proj / ".sulde-config.yaml.example").exists(),
        ))
        results.append(expect(
            "cp:docs_hub_adr_index",
            (proj / "docs-hub" / "ADR" / "INDEX.md").exists(),
        ))
        results.append(expect(
            "cp:harmony_claude_md",
            (proj / "harmony" / "CLAUDE.md.template").exists(),
        ))
        results.append(expect(
            "cp:harmony_aiws_handoff",
            (proj / "harmony" / ".ai-workspace" / "handoff" / "README.md").exists(),
        ))
        installer = proj / "harmony" / "scripts" / "pre-commit-installer.sh"
        if os.name == "nt":
            source = Path("template/harmony/scripts/pre-commit-installer.sh")
            modes, git_error = git_index_modes()
            syntax_ok, syntax_detail = bash_syntax(source, find_git_bash())
            source_ok = modes.get(source.as_posix()) == "100755" and syntax_ok
            results.append(expect(
                "cp:harmony_installer_present",
                installer.is_file() and source_ok,
                git_error or syntax_detail,
            ))
        else:
            results.append(expect(
                "cp:harmony_installer_executable",
                bool(installer.stat().st_mode & 0o111),
                f"mode={oct(installer.stat().st_mode)}",
            ))
    return results


# ─── runner ─────────────────────────────────────────────────────────────────

def main() -> int:
    if not TEMPLATE.exists():
        print(f"FATAL: {TEMPLATE} not found — run from repo root", file=sys.stderr)
        return 1

    all_results: list[Result] = []
    all_results += test_project_root_files()
    all_results += test_stack_files()
    all_results += test_executable_contract()
    all_results += test_stack_command_signatures()
    all_results += test_no_residual_frontend_a()
    all_results += test_copytree_simulation()

    passed = sum(1 for r in all_results if r.ok)
    total = len(all_results)
    print()
    print(f"sulde-cc P2 template dry-run: {passed}/{total} passed")
    print()
    # Group failures separately for readability
    failures = [r for r in all_results if not r.ok]
    if failures:
        print("Failures:")
        for r in failures:
            line = f"  FAIL {r.name}"
            if r.detail:
                line += f"  ({r.detail})"
            print(line)
        print()
    print(f"({passed} pass, {len(failures)} fail)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
