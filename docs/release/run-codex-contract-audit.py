"""Bounded CLI audit; private raw evidence, no production installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts/kb"))
from codex_cli_contract import AUDITED_CODEX_VERSION, codex_probe_spec, canonical_codex_help_observation

SCOPES = {
    "injection": [
        "tests.test_codex_executable_binding",
        "tests.test_native_agent_broker",
        "tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_rejects_path_alias_future_and_substring_versions",
        "tests.test_agent_runtime.AgentRuntimeTests.test_synthetic_incompatible_codex_help_fails_closed",
        "tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_rejects_help_diagnostic_stderr_drift",
        "tests.test_codex_plugin_install.CodexPluginInstallTests.test_installer_cli_smoke_uses_successful_stdout_identity_only",
        "tests.test_candidate_codex_plugin.CandidateDeploymentTests.test_prepare_rejects_unaudited_versions_before_any_candidate_write",
    ],
    "closure": [
        "tests.test_codex_live_contract_audit",
        "tests.test_native_pretool_delivery",
        "tests.test_agent_runtime.AgentRuntimeTests.test_structured_git_lifecycle_provisions_commits_and_fast_forwards",
    ],
    "lifecycle": [
        "tests.test_agent_runtime.AgentRuntimeTests.test_structured_git_lifecycle_provisions_commits_and_fast_forwards",
    ],
    "native": [
        "tests.test_native_posttool_delivery",
        "tests.test_native_control_composition",
        "tests.test_native_session_continuity",
        "tests.test_native_receipt_consistency",
    ],
    "regression": [
        "tests.test_agent_runtime", "tests.test_codex_plugin_install",
        "tests.test_codex_executable_binding", "tests.test_candidate_codex_plugin",
        "tests.test_candidate_promotion_identity", "tests.test_stage_plugin",
        "tests.test_native_agent_broker", "tests.test_native_pretool_delivery",
        "tests.test_codex_hook_bridge", "tests.test_codex_user_prompt_adapter",
        "tests.test_codex_live_contract_audit",
    ],
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("scope", choices=("surfaces", *SCOPES))
    parser.add_argument("run_id")
    parser.add_argument("--expected-version", default=AUDITED_CODEX_VERSION,
                        help="Audit target only; does not alter production version authority")
    parser.add_argument("--output-root", type=Path,
                        default=ROOT / ".sulde/cli-contract-audit")
    parser.add_argument("--resume-evidence", type=Path,
                        help="Reuse only explicit one-line OKs with identical source inputs")
    parser.add_argument("--installer-once", action="store_true",
                        help="Select base installer cases once plus subclass-owned cases")
    args = parser.parse_args()
    if not args.run_id.replace("-", "").isalnum():
        parser.error("invalid run id")
    caller_umask = os.umask(0o077)
    output = args.output_root.resolve() / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    executable = Path(shutil.which("codex")).resolve(strict=True)
    environment = os.environ.copy()
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                       CODEX_CONTRACT_AUDIT_LIVE="1",
                       SULDE_TEST_CODEX_EXECUTABLE=str(executable),
                       SULDE_AUDIT_CURSOR_HOME=str(output / "audit-cursors"))
    # Read-only identity/schema probes do not need user configuration or auth.
    probe_env = dict(environment)
    probe_env["CODEX_HOME"] = str(output / "probe-home")
    (output / "probe-home").mkdir()
    probe = codex_probe_spec(probe_env)
    def capture(argv):
        return subprocess.run(argv, cwd=ROOT, input="", capture_output=True,
                              text=True, env=probe.environment, timeout=45, check=False)
    version = capture([str(executable), "--version"])
    head = capture(["git", "rev-parse", "HEAD"]).stdout.strip()
    tracked = capture(["git", "ls-files", "-z"]).stdout.split("\0")
    tracked += [str(Path(__file__).relative_to(ROOT)),
                "tests/test_codex_live_contract_audit.py"]
    source_hashes = {p: sha(ROOT / p) for p in tracked if p and (ROOT / p).is_file()}
    metadata = {"schema": "sulde-cli-contract-audit-v1", "scope": args.scope,
                "head": head, "cli_path": str(executable), "cli_sha256": sha(executable),
                "expected_version": args.expected_version,
                "cli_version": version.stdout.strip(), "version_exit": version.returncode,
                "source_sha256": source_hashes, "python": sys.executable,
                "test_process_umask": oct(caller_umask),
                "production_install_requested": False,
                "human_approval_simulated_by_fixtures_is_not_live_authority": True}
    started = time.monotonic()
    exit_code = 1
    try:
        if version.returncode or version.stdout.strip() != args.expected_version:
            raise RuntimeError("audit target changed")
        if args.scope == "surfaces":
            rows = []
            for name, argv in (("global", ["--help"]), ("exec", ["exec", "--help"]),
                               ("app-server", ["app-server", "--help"])):
                result = capture([str(executable), *argv])
                (output / (name + ".stdout")).write_text(result.stdout)
                (output / (name + ".stderr")).write_text(result.stderr)
                rows.append((result.returncode, result.stdout, result.stderr))
            _, digest = canonical_codex_help_observation(tuple(rows))
            metadata["help_observation_sha256"] = digest
            schema = capture([str(executable), "app-server", "generate-json-schema",
                              "--experimental", "--out", str(output / "schema")])
            (output / "schema.stdout").write_text(schema.stdout)
            (output / "schema.stderr").write_text(schema.stderr)
            metadata["schema_sha256"] = {str(p.relative_to(output)): sha(p)
                                         for p in sorted((output / "schema").rglob("*.json"))}
            exit_code = schema.returncode
            if not metadata["schema_sha256"]:
                exit_code = 1
        else:
            selected = list(SCOPES[args.scope])
            if args.installer_once or args.resume_evidence:
                sys.path.insert(0, str(ROOT))
                def cases(suite):
                    for item in suite:
                        if isinstance(item, unittest.TestSuite):
                            yield from cases(item)
                        else:
                            yield item
                loaded = list(cases(unittest.defaultTestLoader.loadTestsFromNames(selected)))
                inherited = []
                if args.installer_once:
                    from tests.test_codex_plugin_install import CodexPluginInstallTests
                    unique = []
                    for case in loaded:
                        cls = type(case)
                        if cls is not CodexPluginInstallTests and issubclass(cls, CodexPluginInstallTests):
                            if case._testMethodName not in cls.__dict__:
                                # Only this module's known pure-addition subclasses qualify.
                                overlap = set(cls.__dict__) & set(CodexPluginInstallTests.__dict__)
                                if overlap - {"__module__", "__doc__"}:
                                    raise RuntimeError("installer subclass overrides base behavior")
                                inherited.append({"omitted": case.id(), "covered_by":
                                    "tests.test_codex_plugin_install.CodexPluginInstallTests." + case._testMethodName})
                                continue
                        unique.append(case)
                    loaded = unique
                selected = [case.id() for case in loaded]
                metadata["inherited_duplicates"] = inherited
                metadata["selected_before_reuse"] = list(selected)
                if args.resume_evidence:
                    previous = json.loads((args.resume_evidence / "run.json").read_text())
                    if previous["cli_sha256"] != metadata["cli_sha256"] or previous["cli_version"] != metadata["cli_version"]:
                        raise RuntimeError("prior CLI identity differs")
                    if previous["python"] != metadata["python"] or previous["test_process_umask"] != metadata["test_process_umask"]:
                        raise RuntimeError("prior runner environment differs")
                    checked_sources = [p for p in source_hashes if p.startswith(("scripts/", "tests/"))]
                    if set(checked_sources) != {p for p in previous["source_sha256"] if p.startswith(("scripts/", "tests/"))}:
                        raise RuntimeError("source/test inventory differs")
                    if any(source_hashes[p] != previous["source_sha256"][p] for p in checked_sources):
                        raise RuntimeError("source/test bytes differ; cannot reuse")
                    old_log = args.resume_evidence / "tests.log"
                    if sha(old_log) != previous["log_sha256"]:
                        raise RuntimeError("prior test log drifted")
                    # Do not infer success from partial lines, standalone 'ok', skip,
                    # provider output, suite exit, or an interrupted active case.
                    passed = {f"{cls}.{method}" for method, cls in re.findall(
                        r"^(test_[A-Za-z0-9_]+) \((tests\.[A-Za-z0-9_.]+)\) \.\.\. ok$",
                        old_log.read_text(), flags=re.MULTILINE)}
                    reused = sorted(set(selected) & passed)
                    selected = [name for name in selected if name not in passed]
                    metadata["reuse"] = {"source": str(args.resume_evidence.resolve()),
                                         "log_sha256": sha(old_log), "tests": reused,
                                         "source_files_checked": len(checked_sources)}
            metadata["selected_to_run"] = list(selected)
            if not selected:
                raise RuntimeError("no tests remain; do not invoke discovery accidentally")
            command = [sys.executable, "-B", "scripts/kb/run-isolated-tests.py", *selected]
            metadata["command"] = command
            with (output / "tests.log").open("xb") as log:
                process = subprocess.Popen(command, cwd=ROOT, env=environment,
                                           stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True, umask=caller_umask)
                try:
                    exit_code = process.wait(timeout=600)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    exit_code = 124
            metadata["log_sha256"] = sha(output / "tests.log")
    except Exception as error:
        metadata["error"] = repr(error)
    metadata.update(exit_code=exit_code, elapsed_seconds=round(time.monotonic()-started, 3),
                    cli_identity_unchanged=sha(executable) == metadata["cli_sha256"])
    if not metadata["cli_identity_unchanged"]:
        metadata["exit_code"] = exit_code = 1
    (output / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({key: metadata[key] for key in
                      ("scope", "exit_code", "elapsed_seconds", "cli_identity_unchanged")}))
    print("Evidence: " + str(output))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
