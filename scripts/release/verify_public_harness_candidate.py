#!/usr/bin/env python3
"""Run bounded empty-data and packaging probes on a private export candidate.

No bootstrap installer, scheduler mutation, production home or remote Git
operation is used. These probes do not substitute for full source regression,
privacy review, real host validation or publication approval.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import shutil
import sqlite3
import subprocess
import sys
import time

sys.dont_write_bytecode = True
from export_public_harness import checked_new_directory, digest, encode, verify_tree


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--plugin-validator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extra-pattern", action="append", default=[])
    parser.add_argument("--extra-test", action="append", default=[])
    parser.add_argument("--real-codex", type=Path,
                        help="explicit local CLI for isolated identity/handshake round-trip; no production install")
    parser.add_argument("--full-isolated-suite", action="store_true",
                        help="run the supported OS-isolated full suite, retaining failures and skips")
    parser.add_argument("--production-kb", type=Path,
                        help="existing production KB protected read-only by the full-suite runner")
    args = parser.parse_args()
    production_kb = None
    if args.full_isolated_suite:
        if args.production_kb is None or not args.production_kb.is_absolute():
            parser.error("full suite requires an explicit absolute --production-kb")
        production_kb = args.production_kb.resolve(strict=True)
        if not production_kb.is_dir() or production_kb == Path(production_kb.anchor):
            parser.error("production KB must be an existing non-root directory")
    candidate = args.candidate.resolve(strict=True)
    plan = json.loads((candidate / "review.json").read_bytes())
    verify_tree(candidate / "tree", plan)
    output = checked_new_directory(args.output)
    checkout = output / "checkout"
    shutil.copytree(candidate / "tree", checkout)
    state = output / "state"
    state.mkdir(mode=0o700)
    kb_home = state / "data/kb"
    kb_home.mkdir(parents=True)
    # Do not inherit session authority or production runtime overrides into a
    # synthetic test process. The actual host session is never changed.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("SULDE_", "GIT_"))
                   and key not in {"CODEX_THREAD_ID", "CLAUDE_SESSION_ID", "PYTHONPATH"}}
    environment.update({
        "SULDE_HOME": str(state), "SULDE_KB_HOME": str(kb_home),
        "SULDE_REPO_ROOT": str(checkout), "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1", "HF_HOME": str(state / "hf"),
        "XDG_CACHE_HOME": str(state / "cache"), "TOKENIZERS_PARALLELISM": "false",
    })
    if production_kb is not None:
        environment["SULDE_PRODUCTION_KB_HOME"] = str(production_kb)
    real_codex_identity = None
    if args.real_codex is not None:
        if not args.real_codex.is_absolute():
            raise ValueError("real Codex probe requires an explicit absolute path")
        target = args.real_codex.resolve(strict=True)
        if not target.is_file():
            raise ValueError("real Codex probe requires a regular executable")
        real_codex_identity = {"path": str(target), "sha256": digest(target.read_bytes())}
        environment["SULDE_TEST_CODEX_EXECUTABLE"] = str(target)
    cases = []
    python = str(args.python.absolute())

    def run(name, argv, *, stdin=None, validate=None, timeout=180, test_result=False):
        started = time.monotonic()
        try:
            with subprocess.Popen(argv, cwd=checkout, env=environment, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  encoding="utf-8", errors="replace",
                                  start_new_session=os.name == "posix") as process:
                try:
                    stdout, stderr = process.communicate(stdin, timeout=timeout)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    stdout, stderr = process.communicate()
                    raise subprocess.TimeoutExpired(argv, timeout, stdout, stderr)
                result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired as error:
            def decoded(value):
                return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""
            result = subprocess.CompletedProcess(argv, 124, decoded(error.stdout),
                                                 decoded(error.stderr) + "\nProbe timed out; not reusable success.\n")
        passed = result.returncode == 0
        detail = ""
        test_count = None
        skipped_count = 0
        if "unittest" in argv or test_result:
            counts = re.findall(r"Ran (\d+) tests? in", result.stderr + result.stdout)
            test_count = int(counts[-1]) if counts else 0
            if not test_count:
                passed, detail = False, "No executed tests; empty discovery is not success"
            skipped = re.search(r"skipped=(\d+)", result.stderr + result.stdout)
            skipped_count = int(skipped[1]) if skipped else 0
            if skipped_count:
                passed, detail = False, "Required bounded probe skipped tests; not verification"
        if passed and validate:
            try:
                validate(result.stdout)
            except (AssertionError, ValueError, KeyError, sqlite3.Error) as error:
                passed = False
                detail = type(error).__name__ + ": " + str(error)
        log = (result.stdout + "\n" + result.stderr).encode()
        # Only logs of this synthetic checkout/home are retained, privately.
        (output / f"{name}.log").write_bytes(log)
        case = {"name": name, "passed": passed, "exit_code": result.returncode,
                "seconds": round(time.monotonic() - started, 3),
                "log_sha256": digest(log), "detail": detail}
        if test_count is not None:
            case["tests_run"] = test_count
            case["tests_skipped"] = skipped_count
        cases.append(case)
        print(json.dumps(case), flush=True)
        return passed

    def require(condition, message):
        if not condition:
            raise AssertionError(message)

    # New synthetic Git history only, with no Pro objects, branches or remotes.
    if not run("git-init", ["git", "init", "-q", "--template=", "."]):
        return 1
    if not run("git-add", ["git", "add", "--all"]):
        return 1
    if not run("git-commit", ["git", "-c", "user.name=Public Candidate Test",
                              "-c", "user.email=candidate@example.invalid",
                              "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                              "commit", "-qm", "Synthetic data-free review checkout"]):
        return 1

    def empty_index(_stdout):
        with sqlite3.connect(f"file:{kb_home / 'kb.db'}?mode=ro", uri=True) as connection:
            for table in ("manifest", "chunks", "vectors"):
                require(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0,
                        f"unexpected data in synthetic {table}")

    index_ready = run("empty-index", [python, "-B", "tools/kb-index/build.py", "--full"], validate=empty_index)
    memory_ready = run("empty-memory-init", [python, "-B", "tools/kb-index/memory.py", "init"])
    if index_ready and memory_ready:
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "synthetic-public-probe", "version": "1"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "kb_search", "arguments": {"query": "synthetic empty corpus"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                "name": "memory_search", "arguments": {"query": "synthetic empty memory"}}},
        ]

        def valid_rpc(stdout):
            responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            require([row.get("id") for row in responses] == [1, 2, 3, 4], "missing/out-of-order RPC response")
            require(all("result" in row and "error" not in row for row in responses), "RPC error")
            names = {tool["name"] for tool in responses[1]["result"]["tools"]}
            require({"kb_search", "memory_search", "kb_status"} <= names, "missing MCP capabilities")
            for row in responses[2:]:
                require(not row["result"].get("isError"), "MCP backend returned an error")
                require(json.loads(row["result"]["content"][0]["text"]) == [], "empty store returned data")

        run("mcp-stdio-empty-queries", [python, "-B", "tools/kb-mcp/server.py"],
            stdin="".join(json.dumps(item) + "\n" for item in requests), validate=valid_rpc)

    for pattern in ("test_corpus_manifest.py", "test_kb_index_common.py", "test_kb_mcp_entry.py",
                    "test_knowledge_history.py", "test_public_toolkit.py", *args.extra_pattern):
        if not re.fullmatch(r"test_[a-z0-9_]+\.py", pattern):
            raise ValueError("extra test pattern must be an exact test module filename")
        run(pattern.removesuffix(".py"), [python, "-B", "-m", "unittest", "discover",
                                         "-s", "tests", "-p", pattern, "-v"],
            validate=lambda stdout: None)
    for index, test in enumerate(args.extra_test):
        if not re.fullmatch(r"tests\.[A-Za-z0-9_.]+", test):
            raise ValueError("extra test must be a qualified tests module/class/test")
        run(f"targeted-test-{index}", [python, "-B", "-m", "unittest", "-v", test])
    if real_codex_identity is not None:
        run("real-codex-installed-identity-roundtrip", [python, "-B", "-m", "unittest", "-v",
            "tests.test_agent_runtime.AgentRuntimeTests.test_audited_codex_real_cli_contract"])
        if digest(Path(real_codex_identity["path"]).read_bytes()) != real_codex_identity["sha256"]:
            raise ValueError("real Codex probe input changed during verification")
    artifacts = output / "artifacts"
    for target, platform in (("claude", None), ("codex", "posix"), ("codex", "windows")):
        name = target + ("-" + platform if platform else "")
        artifact = artifacts / name
        argv = [python, "-B", "scripts/release/stage_plugin.py", "--target", target,
                "--output", str(artifact)]
        if platform:
            argv += ["--platform", platform]
        if run("artifact-" + name, argv) and target == "codex":
            run("plugin-validator-" + name, [python, "-B", str(args.plugin_validator.absolute()),
                                             str(artifact / "plugins/sulde")])
    if args.full_isolated_suite:
        run("full-isolated-suite", [python, "-B", "scripts/kb/run-isolated-tests.py"],
            timeout=1800, test_result=True)
    verify_tree(candidate / "tree", plan)
    report = {
        "schema": "sulde-public-candidate-probes-v1", "release_ready": False,
        "manifest_sha256": plan["manifest_sha256"], "cases": cases,
        "verifier_sha256": digest(Path(__file__).read_bytes()),
        "real_codex_identity": real_codex_identity,
        "full_suite_attempted": args.full_isolated_suite,
        "all_bounded_probes_passed": all(case["passed"] for case in cases),
        "not_covered": (["full-source-regression"] if not args.full_isolated_suite else [])
                       + ["privacy-review", "bootstrap-installation", "live-host-hooks",
                          "Windows-execution", "public-push"],
    }
    (output / "results.json").write_bytes(encode(report))
    return 0 if report["all_bounded_probes_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
