"""B1/B2 instrumented runtime entry; fake provider, isolated synthetic state.

Only Popen/real stdin is instrumented: wait for the actual provider/watchdog to
exit before the original runtime writes. No monitor/callback/consumer replacement.
--pair archives both frozen versions; exit reflects candidate, not old failures.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_r3_normal_pair import VERSIONS, digest, require, save_process, write_json


def fixture():
    import test_r3_real_entry_chain as chain
    return chain


class B1PrerequisiteFailed(AssertionError):
    """B2 was not reached because the real B1 output already violated safety."""


def runtime_boundary_entry(argv):
    runtime, receipt, provider, *arguments = argv
    receipt = Path(receipt)
    real_popen = subprocess.Popen
    facts = {"boundary": "Popen/real-stdin", "provider": provider, "writes": []}

    class StdinObserver:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def invoke(self, method, *args):
            try:
                return getattr(self.stream, method)(*args)
            except OSError as error:
                facts["writes"].append({"method": method, "error": type(error).__name__,
                                        "errno": error.errno, "message": str(error)})
                write_json(receipt, facts)
                raise

        def write(self, value):
            facts["prompt_contains_feedback"] = "监督端预测对照反馈" in value
            return self.invoke("write", value)

        def close(self):
            return self.invoke("close")

    def spawn(command, *args, **kwargs):
        process = real_popen(command, *args, **kwargs)
        if isinstance(command, (tuple, list)) and provider in map(str, command):
            try:
                facts["exit_before_input"] = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise
            facts["pid"] = process.pid
            require(process.stdin is not None, "provider has no stdin pipe")
            process.stdin = StdinObserver(process.stdin)
            write_json(receipt, facts)
        return process

    subprocess.Popen = spawn
    sys.path.insert(0, str(Path(runtime).parent))
    sys.argv = [runtime, *arguments]
    try:
        runpy.run_path(runtime, run_name="__main__")
    finally:
        subprocess.Popen = real_popen


def events(chain):
    return [json.loads(line) for path in sorted(chain.state.glob("*.run.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def snapshot(chain, output):
    shutil.copytree(chain.state, output / "state", symlinks=True)
    for name in ("value.py", "consumer.py"):
        shutil.copyfile(chain.worktree / name, output / name)
    if chain.prompt_capture.exists():
        shutil.copyfile(chain.prompt_capture, output / "provider.stdin")


def registry(chain):
    path = chain.state / "prediction-feedback-consumed.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def prepare_failure(chain, output):
    mod = fixture()
    chain.seed_prediction()
    first = chain.run()
    save_process(output, "prepare", first)
    require(first.returncode != 0, "feedback preparation did not fail")
    artifact = chain.state / f"prediction-feedback-{mod.ip.digest('embed')}.json"
    pending_bytes = artifact.read_bytes()
    pending = json.loads(pending_bytes)
    require(pending["task_id_sha256"] == mod.ip.digest("embed"), "wrong task")
    require(pending["verdict"] == "larger_than_predicted", "wrong source feedback")
    source = [row for row in events(chain) if row["type"] == "prediction.feedback"]
    require(len(source) == 1 and source[0]["payload"]["status"] == "checked", "missing source observation")
    require(pending["run_id_sha256"] == mod.ip.digest(source[0]["run_id"]), "wrong source run")
    write_json(output / "source-feedback.json", pending)
    # Same executable path; only the synthetic provider behavior changes.
    chain.executable.write_text("#!/usr/bin/python3\nimport os\nos.close(0)\n", encoding="utf-8")
    signal = output / "pipe-boundary.json"
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--runtime-boundary",
               str(mod.RUNTIME), str(signal), str(chain.executable), "run",
               str(chain.worktree), "embed", str(chain.brief), "--timeout", "15",
               "--task-id", "embed", "--retry", "--retry-op", "pipe-failure"]
    failed = subprocess.run(command, env=chain.environment(), capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=30)
    save_process(output, "fault", failed)
    boundary = json.loads(signal.read_text(encoding="utf-8"))
    require(boundary["exit_before_input"] == 0, "provider did not exit before send")
    require(boundary["prompt_contains_feedback"], "fault did not reach feedback send")
    require(any(item["error"] == "BrokenPipeError" for item in boundary["writes"]), "no real EPIPE")
    require(failed.returncode != 0, "send failure swallowed by runtime")
    request = pending["request_id"]
    rows = [row for row in events(chain) if row["type"] == "prediction.feedback_consumed"
            and row["payload"].get("request_id") == request]
    require(len(rows) == 1, "fault did not traverse actual callback exactly once")
    reg = registry(chain)
    observation = {
        "request_id": request, "source_run_sha256": pending["run_id_sha256"],
        "callback_run_id": rows[0]["run_id"],
        "failure_recorded": bool(rows[0]["payload"].get("send_failed")),
        "unconfirmed": request in reg.get("send_unconfirmed", {}),
        "consumed": request in reg.get("consumed", {}),
        "artifact_preserved": artifact.exists() and artifact.read_bytes() == pending_bytes,
    }
    write_json(output / "b1-observation.json", observation)
    snapshot(chain, output / "after-fault")
    return artifact, pending, observation


def require_b1(observation):
    if not (observation["failure_recorded"] and observation["unconfirmed"]
            and not observation["consumed"] and observation["artifact_preserved"]):
        raise B1PrerequisiteFailed("B1 invariant failed: " + json.dumps(observation))


def scenario(case, output):
    mod = fixture()
    with tempfile.TemporaryDirectory(prefix="sulde-injection-") as tmp:
        chain = mod._Chain(Path(tmp), mode="markerdriven")
        try:
            artifact, pending, observation = prepare_failure(chain, output)
            require_b1(observation)
            if case == "b1":
                return
            chain._provider(chain.executable.parent, "markerdriven")
            request = pending["request_id"]
            unrelated = chain.state / f"prediction-feedback-{mod.ip.digest('other')}.json"
            unrelated.write_text('{"request_id":"unrelated"}\n', encoding="utf-8")
            unrelated_bytes = unrelated.read_bytes()
            preview, reason = mod.pf.load_pending_feedback(
                state_dir=chain.state, task_id="embed", contract_version="l3:embed#1")
            write_json(output / "blocked-preview.json", {"feedback": preview, "reason": reason})
            require(preview is None and "send result uncertain" in reason, "wrong B2 gate")
            if case == "b2_blocked":
                chain.prompt_capture.unlink()
                blocked = chain.run(retry_op="uncertain-without-recovery")
                save_process(output, "blocked", blocked)
                prompt = chain.captured_prompt()  # Must be NEW provider output.
                require(mod.FEEDBACK_MARKER not in prompt, "uncertain feedback was sent")
                require(request not in registry(chain).get("consumed", {}), "uncertain request consumed")
                after = json.loads(artifact.read_text(encoding="utf-8")) if artifact.exists() else None
                write_json(output / "after-blocked-feedback.json", after)
                next_feedback, next_reason = mod.pf.load_pending_feedback(
                    state_dir=chain.state, task_id="embed", contract_version="l3:embed#1")
                write_json(output / "next-preview.json", {"feedback": next_feedback, "reason": next_reason})
                require(unrelated.read_bytes() == unrelated_bytes, "unrelated task changed")
                require(after is not None and after["request_id"] == request,
                        "B2 pending request overwritten before recovery")
                require(after == pending, "B2 pending payload changed before recovery")
                require(next_feedback is None and "send result uncertain" in next_reason,
                        "B2 recovery gate lost after completion")
                disclosures = [row["payload"] for row in events(chain)
                               if row["type"] == "prediction.feedback"]
                require(disclosures[-1]["feedback"]["disposition"] == "preserved_send_unconfirmed",
                        "missing preserved-feedback disclosure")
                # Recovery must still work after a blocked run, not only in a
                # fresh fork immediately following the send failure.
                mod.pf.mark_feedback_recovered(state_dir=chain.state, task_id="embed",
                    request_id=request, decision="retry", at="2026-09-28T00:00:00+00:00")
                resumed = chain.run(retry_op="recovery-after-blocked-run")
                save_process(output, "recovered-after-blocked", resumed)
                require(resumed.returncode == 0, resumed.stdout + resumed.stderr)
                require(request in registry(chain).get("consumed", {}), "old request never consumed after recovery")
                probe = chain.probe()
                save_process(output, "probe-after-blocked", probe)
                require(probe.returncode == 0 and probe.stdout.strip() == "ok 2", "post-blocked recovery failed")
            else:
                require(hasattr(mod.pf, "mark_feedback_recovered"), "recovery API unavailable")
                mod.pf.mark_feedback_recovered(state_dir=chain.state, task_id="embed",
                    request_id=request, decision="retry", at="2026-09-28T00:00:00+00:00")
                chain.prompt_capture.unlink()
                resumed = chain.run(retry_op="explicit-recovery")
                save_process(output, "recovered", resumed)
                require(resumed.returncode == 0, resumed.stdout + resumed.stderr)
                prompt = chain.captured_prompt()
                require(mod.FEEDBACK_MARKER in prompt and all(f in prompt for f in pending["facts"]),
                        "recovered facts not sent")
                reg = registry(chain)
                summary = json.loads((chain.state / "embed.guardian.json").read_text(encoding="utf-8"))
                require(reg["consumed"][request]["consuming_run_id_sha256"] ==
                        mod.ip.digest(summary["execution"]["run_id"]), "wrong recovery consumer")
                require(not artifact.exists(), "consumed artifact remains")
                probe = chain.probe()
                save_process(output, "probe", probe)
                require(probe.returncode == 0 and probe.stdout.strip() == "ok 2", "recovery probe failed")
            require(unrelated.read_bytes() == unrelated_bytes, "unrelated task changed")
        finally:
            snapshot(chain, output / "final")


def worker(source, output):
    os.environ["SULDE_R3_SOURCE_ROOT"] = str(source)
    mod = fixture()
    require(Path(mod.pf.__file__).resolve().parent == source / "scripts/kb", "wrong module source")
    require(Path(mod.ip.__file__).resolve().parent == source / "scripts/kb", "wrong prediction source")
    identities = {name: {"path": str(source / "scripts/kb" / name),
                         "sha256": digest(source / "scripts/kb" / name)}
                  for name in ("agent-runtime.py", "prediction_feedback.py", "impact_prediction.py")}
    write_json(output / "identity.json", identities)
    results = {}
    for case in ("b1", "b2_blocked", "b2_recovered"):
        dest = output / case
        dest.mkdir()
        try:
            scenario(case, dest)
            results[case] = {"passed": True, "status": "passed"}
        except Exception as error:
            (dest / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
            results[case] = {"passed": False, "error": str(error),
                             "status": ("not_reached_b1_failed" if case != "b1"
                                        and isinstance(error, B1PrerequisiteFailed) else "failed")}
    require(all(digest(Path(row["path"])) == row["sha256"] for row in identities.values()),
            "source mutated during test")
    require(not list(source.rglob("*.pyc")), "source polluted with bytecode")
    write_json(output / "results.json", results)
    return 0 if all(r["passed"] for r in results.values()) else 1


def run_pair(output, versions=None):
    output.mkdir(parents=True, exist_ok=False)
    for name in (Path(__file__).name, "test_r3_real_entry_chain.py", "test_r3_normal_pair.py"):
        shutil.copyfile(ROOT / "tests" / name, output / name)
    results = {}
    for label, revision in (versions or VERSIONS).items():
        oid = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify",
                              "--end-of-options", f"{revision}^{{commit}}"],
                             check=True, capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout.strip()
        dest = output / label
        dest.mkdir()
        with tempfile.TemporaryDirectory(prefix="sulde-injection-source-") as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            archive = subprocess.run(["git", "-C", str(ROOT), "archive", oid], check=True, capture_output=True)
            subprocess.run(["tar", "-x", "-C", str(source)], input=archive.stdout, check=True)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("SULDE_", "CODEX_", "CLAUDE_", "PYTHON"))}
            env.update(PYTHONDONTWRITEBYTECODE="1", SULDE_HOME=str(Path(tmp) / "home"),
                       SULDE_KB_DATA_ROOT=str(Path(tmp) / "home/data/kb"))
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                "--worker", str(source), "--output", str(dest)], env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=120)
            save_process(dest, "worker", result)
            results[label] = {"oid": oid, "exit": result.returncode,
                              "cases": json.loads((dest / "results.json").read_text(encoding="utf-8"))}
    write_json(output / "summary.json", results)
    manifest = "".join(f"{digest(p)}  {p.relative_to(output).as_posix()}\n"
                       for p in sorted(output.rglob("*")) if p.is_file() and not p.is_symlink())
    (output / "sha256.txt").write_text(manifest, encoding="utf-8")
    return results["candidate"]["exit"]


class InjectionTests(unittest.TestCase):
    def check_case(self, case):
        with tempfile.TemporaryDirectory() as tmp:
            scenario(case, Path(tmp))

    def test_normal_in_scope_change(self):
        mod = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            chain = mod._Chain(Path(tmp), mode="wellbehaved")
            chain.seed_prediction()
            result = chain.run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(chain.feedback_events()[0]["payload"]["verdict"], "as_predicted")
            probe = chain.probe()
            self.assertEqual((probe.returncode, probe.stdout.strip()), (0, "ok 2"))

    def test_stdin_failure_preserves_artifact_and_records_failure(self):
        self.check_case("b1")

    def test_send_unconfirmed_blocks_re_delivery(self):
        self.check_case("b2_blocked")

    def test_explicit_recovery_delivers_exact_request(self):
        self.check_case("b2_recovered")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--runtime-boundary":
        runtime_boundary_entry(sys.argv[2:])
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--pair", type=Path)
        parser.add_argument("--worker", type=Path)
        parser.add_argument("--output", type=Path)
        parser.add_argument("--baseline", default=VERSIONS["old"])
        parser.add_argument("--candidate", default=VERSIONS["candidate"])
        args = parser.parse_args()
        if args.worker:
            raise SystemExit(worker(args.worker.resolve(), args.output.resolve()))
        if not args.pair:
            parser.error("--pair <new evidence directory> required")
        raise SystemExit(run_pair(args.pair.resolve(), {"old": args.baseline, "candidate": args.candidate}))
