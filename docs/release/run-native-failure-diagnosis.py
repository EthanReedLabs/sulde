"""Bounded diagnostic/regression runner: complete logs and real exit code.

Outputs remain private under .sulde; no production install or external model request.
The two native tests own disposable candidate homes and a loopback model fixture.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
TESTS = [
    "tests/test_isolated_test_runner.py::IsolatedTestRunnerTests::test_os_boundary_blocks_non_python_write_before_file_appears",
    "tests/test_native_control_composition.py::NativeControlCompositionTests::test_real_safe_batches_negative_and_partial_failure",
    "tests/test_native_session_continuity.py::NativeSessionContinuityTests::test_denied_call_does_not_lock_the_following_ordinary_call",
]


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--tmp-root")
    parser.add_argument("--scope", choices=("historical", "boundary", "consumers"), default="historical")
    parser.add_argument("--continuity-evidence", action="store_true",
                        help="rerun only continuity with failure-only observation")
    args = parser.parse_args()
    if not args.run_id.replace("-", "").isalnum():
        raise SystemExit("invalid run id")
    import pytest
    import yaml
    output = ROOT / ".sulde/native-failure-diagnosis" / args.run_id
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    tests = TESTS
    if args.scope == 'boundary':
        tests = ['tests/test_isolated_test_runner.py', 'tests/test_native_canary_boundary.py',
                 'tests/test_repository_relocation.py::RepositoryRelocationFixtureLifecycleTests',
                 'tests/test_candidate_codex_plugin.py']
        env['SULDE_REQUIRE_NATIVE_OS_EVIDENCE'] = '1'
    elif args.scope == 'consumers':
        tests = ['tests/test_native_session_continuity.py', 'tests/test_native_memory_consistency.py',
                 'tests/test_guardian_string_flow.py']
    if args.tmp_root:
        tmp = Path(args.tmp_root).resolve()
        if not tmp.is_relative_to(Path("/private/tmp")):
            raise SystemExit("relocated diagnostic root must be under /private/tmp")
        tmp.mkdir(parents=True, exist_ok=True, mode=0o700)
        env.update(TMPDIR=str(tmp), TMP=str(tmp), TEMP=str(tmp))
    command = [sys.executable, "-B", "-m", "pytest", "-vv", "-s", "--tb=long",
               "-p", "no:cacheprovider", "--junitxml=" + str(output / "results.xml"), *tests]
    if args.continuity_evidence:
        if args.scope != 'historical':
            parser.error('continuity observer requires historical scope')
        command = command[:-len(tests)] + ["-p", "native_failure_evidence", TESTS[-1]]
        env["PYTHONPATH"] = str(Path(__file__).parent) + os.pathsep + env.get("PYTHONPATH", "")
        env["SULDE_DIAGNOSTIC_FAILURE_OUTPUT"] = str(output / "native-failure.json")
    def capture(argv):
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    metadata = {
        "schema": "sulde-native-failure-diagnosis-v1",
        "run_id": args.run_id, "command": command,
        "head": capture(["git", "rev-parse", "HEAD"]),
        "python": sys.executable, "python_version": sys.version,
        "pytest": pytest.__version__, "pyyaml": yaml.__version__,
        "platform": platform.platform(), "tmpdir": env.get("TMPDIR"),
        "codex": shutil.which("codex"), "codex_version": capture(["codex", "--version"]),
        "test_sha256": {item.split("::")[0]: hashlib.sha256(
            (ROOT / item.split("::")[0]).read_bytes()).hexdigest() for item in tests},
        'scope': args.scope,
        'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in ('scripts/kb/run-isolated-tests.py',
                                       'scripts/release/native_pretool_canary.py')},
        'native_os_evidence_required': env.get('SULDE_REQUIRE_NATIVE_OS_EVIDENCE') == '1',
        "production_install_requested": False,
        "model_transport": "existing test-owned loopback fixture",
        "failure_only_observer": args.continuity_evidence,
    }
    started = time.monotonic()
    log_path = output / "pytest.log"
    with log_path.open("xb") as log:
        os.chmod(log_path, 0o600)
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            exit_code = process.wait(timeout=300)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            exit_code = 124
    metadata.update(exit_code=exit_code, elapsed_seconds=round(time.monotonic()-started, 3),
                    log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest())
    result_path = output / "run.json"
    result_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    os.chmod(result_path, 0o600)
    print(json.dumps({"run_id": args.run_id, "exit_code": exit_code,
                      "elapsed_seconds": metadata["elapsed_seconds"], "evidence": str(output)}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
