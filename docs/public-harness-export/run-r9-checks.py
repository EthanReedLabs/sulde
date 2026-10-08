"""Bounded R9 checks using the repository's real OS test isolation boundary."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
UNITS = [
    "tests.test_candidate_codex_plugin",
    "tests.test_codex_plugin_install",
    "tests.test_codex_executable_binding",
    "tests.test_stage_plugin",
    *["tests.test_agent_runtime.AgentRuntimeTests." + name for name in (
        "test_runtime_imports_exact_shared_codex_cli_authority",
        "test_shared_codex_help_observation_normalizes_environment_and_exact_warning",
        "test_codex_preflight_requires_profile_parse_and_app_server_handshake",
        "test_synthetic_incompatible_codex_help_fails_closed",
        "test_codex_preflight_rejects_help_diagnostic_stderr_drift",
        "test_codex_preflight_rejects_path_alias_future_and_substring_versions",
        "test_installed_native_authority_digest_binds_profile_broker_and_generation",
        "test_installed_native_authority_readback_rejects_generation_profile_and_broker_drift",
        "test_native_boundary_injects_all_owned_path_escape_classes",
    )],
]
HOST = ["tests.test_agent_runtime.AgentRuntimeTests." + name for name in (
    "test_audited_codex_real_cli_contract",
    "test_audited_codex_help_observation_matches_real_pty_and_nonpty_parents",
)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("unit", "host"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--production-kb", type=Path, required=True)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--test", action="append", default=[],
                        help="exact scoped unittest target for a follow-up regression")
    args = parser.parse_args()
    output = args.output.absolute()
    if output.exists() or not output.resolve().is_relative_to(ROOT / ".sulde/public-export"):
        raise ValueError("use a fresh task-owned evidence directory")
    executable = args.codex.resolve(strict=True)
    identity = hashlib.sha256(executable.read_bytes()).hexdigest()
    output.mkdir(parents=True, mode=0o700)
    isolation = runpy.run_path(str(ROOT / "scripts/kb/run-isolated-tests.py"))
    environment = isolation["isolated_environment"](
        output / "environment", production_kb=args.production_kb.resolve(strict=True))
    environment["SULDE_TEST_CODEX_EXECUTABLE"] = str(executable)
    started = time.monotonic()
    tests = args.test or (UNITS if args.mode == "unit" else HOST)
    status, code = "failed", 3
    detail = ""
    try:
        isolation["preflight_os_test_isolation"](args.production_kb, environment)
        command = isolation["os_isolated_test_command"](
            [sys.executable, "-B", "-m", "unittest", "-v", *tests], args.production_kb)
        completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=420)
        code = completed.returncode
        log = completed.stdout + "\n" + completed.stderr
        violations = isolation["process_guard_violations"](environment)
        unchanged = hashlib.sha256(executable.read_bytes()).hexdigest() == identity
        import re
        count = re.search(r"Ran (\d+) tests? in", log)
        skips = re.search(r"skipped=(\d+)", log)
        passed = code == 0 and count and int(count[1]) > 0 and not skips and not violations and unchanged
        status = "passed" if passed else "failed"
        (output / "tests.log").write_text(log, encoding="utf-8")
        detail = {"tests_run": int(count[1]) if count else 0,
                  "skipped": int(skips[1]) if skips else 0,
                  "production_write_violations": len(violations), "cli_unchanged": unchanged,
                  "log_sha256": hashlib.sha256(log.encode()).hexdigest()}
    except subprocess.TimeoutExpired as error:
        def decoded(value):
            return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""
        partial = decoded(error.stdout) + "\n" + decoded(error.stderr)
        (output / "tests.log").write_text(partial, encoding="utf-8")
        detail = {"error": "timed out; partial output is not reusable success",
                  "log_sha256": hashlib.sha256(partial.encode()).hexdigest()}
        code = 124
    except RuntimeError as error:
        detail = str(error)
    result = {"status": status, "mode": args.mode, "exit_code": code,
              "seconds": round(time.monotonic() - started, 3), "detail": detail,
              "cli_sha256": identity, "test_targets": tests,
              "external_model_calls": 0, "production_install_performed": False}
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), flush=True)
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
