#!/usr/bin/env python3
"""Command-effect hook-chain probe v2 (isolated, asserting, bytecode-clean).

Improvements over v1 (per acceptance round 2026-09-27 #2):
- Reads ledger rows via the REAL schema {schema, contract:{}, decision:{}, event:{}}
  (v1 wrongly read top-level `effect`, which does not exist -> empty lists).
- Asserts exit codes, structured permission decisions and expected behavior;
  exits non-zero on any mismatch.
- Adds a Pre -> actual execution -> Post chain on side-effect-free fixtures
  (a trivial unittest under vpn-deploy/personal-fleet/tests and an echo-only
  unknown script) and asserts no external_write debt is created in
  runtime.completed_calls / pending_verifications.
- True negatives (deploy/scp/HTTP-write/destructive) are judged only; never executed.
- Bytecode hygiene: sys.dont_write_bytecode + PYTHONDONTWRITEBYTECODE for every
  child; snapshot/verify of source and candidate trees is done by the driver.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

SRC = Path(sys.argv[1]).resolve()   # tree under test (hooks/ + scripts/)
OUT = Path(sys.argv[2]).resolve()   # transcript output (outside SRC)
OUT.parent.mkdir(parents=True, exist_ok=True)

ENTRY_PRE = SRC / "hooks" / "pre_tool_use.py"
ENTRY_POST = SRC / "hooks" / "post_tool_use.py"

UNITTEST_CMD = (
    "python3 -B -m unittest discover "
    "-s vpn-deploy/personal-fleet/tests -p test_chatgpt_trial.py -v"
)
UNKNOWN_CMD = "./fixture-bin/mystery-tool.sh --plan input.json"

# (name, command, kind)  kind: judge-negative | execute-positive
CASES = [
    ("C1-unittest-vpn-deploy-path", UNITTEST_CMD, "execute-positive"),
    ("C6-unknown-script", UNKNOWN_CMD, "execute-positive"),
    ("C2-real-deploy-shape", "deploy --env production --config fleet.yaml", "judge-negative"),
    ("C3-scp-upload", "scp report.txt backup@example.com:/srv/incoming/report.txt", "judge-negative"),
    ("C4-http-write", "curl -X POST -H 'Content-Type: application/json' -d '{\"k\":1}' https://api.example.com/v1/items", "judge-negative"),
    ("C5-destructive", "rm -rf ./build/output", "judge-negative"),
]

FAILURES: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> bool:
    ok = bool(cond)
    if not ok:
        FAILURES.append(f"{label}: {detail}")
    return ok


def run_hook(entry: Path, payload: dict, project: Path, home: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update({
        "SULDE_HOME": str(home),
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return subprocess.run(
        [sys.executable, "-B", str(entry)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(project), env=env, timeout=60, check=False,
    )


def decision_of(proc: subprocess.CompletedProcess) -> dict:
    """Parse the structured permission decision from hook stdout, if any."""
    if not proc.stdout.strip():
        return {}
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return {}
    return out.get("hookSpecificOutput") or {}


def contract_runtime(home: Path, project: Path, src: Path) -> tuple[dict, Path]:
    sys.path.insert(0, str(src / "scripts" / "kb"))
    try:
        import intent_guardian_parts.state as state
        contract_path = state.active_contract_path(home / "data" / "kb", project)
        runtime = json.loads(contract_path.read_text(encoding="utf-8"))["runtime"]
        return runtime, state.audit_path(contract_path)
    finally:
        sys.path.pop(0)


def ledger_rows(events_path: Path) -> list[dict]:
    """Extract per the real ledger schema: rows are {contract, decision, event}."""
    rows = []
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = row.get("event") or {}
            dec = row.get("decision") or {}
            rows.append({
                "schema": row.get("schema"),
                "event_effect": ev.get("effect"),
                "event_id": ev.get("event_id"),
                "session_id": ev.get("session_id"),
                "decision_action": dec.get("action"),
                "reason_code": dec.get("reason_code"),
                "verification": dec.get("verification"),
            })
    return rows


def setup(project: Path) -> None:
    (project / "vpn-deploy" / "personal-fleet" / "tests").mkdir(parents=True)
    (project / "vpn-deploy" / "personal-fleet" / "tests" / "test_chatgpt_trial.py").write_text(
        "import unittest\n\n"
        "class TestChatGptTrial(unittest.TestCase):\n"
        "    def test_noop(self):\n"
        "        self.assertTrue(True)\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )
    bin_dir = project / "fixture-bin"
    bin_dir.mkdir()
    script = bin_dir / "mystery-tool.sh"
    script.write_text("#!/bin/sh\necho fixture-ok\n", encoding="utf-8")
    script.chmod(0o755)
    (project / ".sulde-config.yaml").write_text(
        "enabled: true\nrole: coordinator\ndocs_hub: ./docs-hub\nfrontends: []\n"
        "enforcement_level: balanced\nenforcement_grace_period_days: 7\nlang: en\n",
        encoding="utf-8",
    )


def write_contract(home: Path, project: Path, src: Path) -> Path:
    sys.path.insert(0, str(src / "scripts" / "kb"))
    try:
        os.environ["SULDE_HOME"] = str(home)
        import intent_guardian_parts.state as state
        contract = state.default_contract(
            intent_id="command-effect-probe-v2",
            objective="probe command effect classification through the real hook chain",
            acceptance_criteria=["classification observable"],
            workspace=project,
            mode="enforce",
            allowed_paths=[str(project)],
            confirmed_by="probe",
        )
        # mirror production shape: external writes are confirmable, not pre-denied
        contract["permissions"]["external_write"] = "confirm"
        contract["permissions"]["destructive"] = "deny"
        path = state.active_contract_path(home / "data" / "kb", project)
        path.parent.mkdir(parents=True, exist_ok=True)
        state.write_contract(path, contract)
        return path
    finally:
        sys.path.pop(0)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ce-probe2-") as tmp:
        tmp = Path(tmp)
        project = tmp / "proj"
        project.mkdir()
        setup(project)
        home = tmp / "sulde-home"
        (home / "data" / "kb").mkdir(parents=True)
        contract_path = write_contract(home, project, SRC)

        transcript = {
            "src": str(SRC),
            "project": str(project),
            "sulde_home": str(home),
            "contract": str(contract_path),
            "external_write_perm": "confirm",
            "cases": [],
        }
        baseline_calls: list = []
        for name, command, kind in CASES:
            record: dict = {"name": name, "command": command, "kind": kind}
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(project),
                "session_id": f"probe2-{name}",
                "client": "claude",
            }
            pre = run_hook(ENTRY_PRE, payload, project, home)
            record["pre_exit"] = pre.returncode
            record["pre_decision"] = decision_of(pre)
            record["pre_denied"] = record["pre_decision"].get("permissionDecision") == "deny"

            if kind == "judge-negative":
                check(pre.returncode == 0, f"{name}/pre-exit", f"exit={pre.returncode} err={pre.stderr[:200]}")
                check(record["pre_denied"], f"{name}/expect-deny",
                      f"decision={json.dumps(record['pre_decision'], ensure_ascii=False)[:200]}")
                # judged only: never executed, no Post phase
            else:
                check(pre.returncode == 0, f"{name}/pre-exit", f"exit={pre.returncode} err={pre.stderr[:200]}")
                check(not record["pre_denied"], f"{name}/expect-not-denied",
                      f"decision={json.dumps(record['pre_decision'], ensure_ascii=False)[:200]}")
                if record["pre_denied"] or pre.returncode != 0:
                    # v3 guard: a denied or failed Pre must never execute the
                    # command nor call Post.  Any debt already created at Pre
                    # is attributable to Pre-phase classification alone.
                    record["skipped_after_pre"] = True
                    runtime, events_path = contract_runtime(home, project, SRC)
                    record["pending_at_pre"] = [
                        row for row in (runtime.get("pending_verifications") or [])
                        if isinstance(row, dict) and row.get("session_id") == payload["session_id"]
                    ]
                    record["ledger_session"] = [
                        row for row in ledger_rows(events_path)
                        if row.get("session_id") == payload["session_id"]
                    ]
                    transcript["cases"].append(record)
                    print(
                        f"{name}: pre_exit={record['pre_exit']} denied={record['pre_denied']} "
                        f"-> execution and Post skipped (guard); "
                        f"pending_at_pre={len(record['pending_at_pre'])}",
                        file=sys.stderr,
                    )
                    continue
                # actual execution in the isolated fixture (no external side effects)
                executed = subprocess.run(
                    command, shell=True, cwd=str(project),
                    capture_output=True, text=True, timeout=60, check=False,
                )
                record["exec_exit"] = executed.returncode
                check(executed.returncode == 0, f"{name}/fixture-exec",
                      f"exit={executed.returncode} err={executed.stderr[:200]}")
                post_payload = dict(payload)
                post_payload["tool_response"] = {
                    "stdout": executed.stdout[-2000:],
                    "stderr": executed.stderr[-2000:],
                }
                post = run_hook(ENTRY_POST, post_payload, project, home)
                record["post_exit"] = post.returncode
                check(post.returncode == 0, f"{name}/post-exit",
                      f"exit={post.returncode} err={post.stderr[:200]}")

                runtime, events_path = contract_runtime(home, project, SRC)
                session_calls = [
                    row for row in (runtime.get("completed_calls") or [])
                    if isinstance(row, dict) and row.get("session_id") == payload["session_id"]
                ]
                session_pend = [
                    row for row in (runtime.get("pending_verifications") or [])
                    if isinstance(row, dict) and row.get("session_id") == payload["session_id"]
                ]
                record["completed_calls"] = session_calls
                session_rows = [
                    row for row in ledger_rows(events_path)
                    if row.get("session_id") == payload["session_id"]
                ]
                record["ledger_session"] = session_rows
                session_effects = sorted({row.get("event_effect") for row in session_rows})
                record["ledger_effects"] = session_effects
                effects = sorted({row.get("effect") for row in session_calls})
                record["completed_effects"] = effects
                # positive classification evidence through the real chain
                check("unknown" in session_effects, f"{name}/classified-unknown",
                      f"ledger_effects={session_effects} rows={json.dumps(session_rows, ensure_ascii=False)[:300]}")
                check("external_write" not in session_effects, f"{name}/no-external-write-classification",
                      f"ledger_effects={session_effects}")
                check(all(row.get("verification") == "none" for row in session_rows),
                      f"{name}/no-verification-burden",
                      f"rows={json.dumps(session_rows, ensure_ascii=False)[:300]}")
                # debt must not exist in any durable surface
                check("external_write" not in effects, f"{name}/no-external-write-debt",
                      f"completed_effects={effects} calls={json.dumps(session_calls, ensure_ascii=False)[:300]}")
                check(all(row.get("effect") != "external_write" for row in session_pend),
                      f"{name}/no-pending-external-write",
                      f"pending={json.dumps(session_pend, ensure_ascii=False)[:300]}")
                if not session_calls:
                    # non-material shape: the ledger observation IS the durable proof
                    check(all(row.get("reason_code") == "non_material_observation"
                              for row in session_rows),
                          f"{name}/non-material-proof",
                          f"rows={json.dumps(session_rows, ensure_ascii=False)[:300]}")
            transcript["cases"].append(record)
            print(
                f"{name}: pre_exit={record['pre_exit']} "
                f"denied={record.get('pre_denied')} "
                f"ledger_effects={record.get('ledger_effects', 'n/a (judge-only)')} "
                f"completed_effects={record.get('completed_effects', 'n/a (judge-only)')}",
                file=sys.stderr,
            )
        transcript["failures"] = FAILURES
        OUT.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
        if FAILURES:
            print(f"PROBE FAILED ({len(FAILURES)} assertions):", file=sys.stderr)
            for failure in FAILURES:
                print(f"  - {failure}", file=sys.stderr)
            return 1
        print(f"PROBE PASSED: {len(CASES)} cases, transcript {OUT}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
