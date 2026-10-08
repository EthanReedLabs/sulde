#!/usr/bin/env python3
"""Command-effect hook-chain probe (isolated SULDE_HOME, real hook entry).

Runs the actual hooks/pre_tool_use.py entrypoint against a disposable project
and disposable SULDE_HOME with an enforce-mode workspace contract
(external_write=deny, destructive=deny).  Observable chain signals per case:

- stdout deny JSON from the real hook (misclassification => external_write deny)
- the contract's own events ledger (audit_path), recorded by the real chain

No command is ever executed by this probe: the hook only classifies.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(sys.argv[1]).resolve()  # tree under test (hooks/ + scripts/)
OUT = Path(sys.argv[2]).resolve()  # transcript output file
EXTERNAL_WRITE_PERM = sys.argv[3] if len(sys.argv) > 3 else "deny"
OUT.parent.mkdir(parents=True, exist_ok=True)

ENTRY = SRC / "hooks" / "pre_tool_use.py"

CASES = [
    ("C1-unittest-vpn-deploy-path",
     "python3 -B -m unittest discover -s vpn-deploy/personal-fleet/tests -p test_chatgpt_trial.py -v"),
    ("C2-real-deploy-shape",
     "deploy --env production --config fleet.yaml"),
    ("C3-scp-upload",
     "scp report.txt backup@example.com:/srv/incoming/report.txt"),
    ("C4-http-write",
     "curl -X POST -H 'Content-Type: application/json' -d '{\"k\":1}' https://api.example.com/v1/items"),
    ("C5-destructive",
     "rm -rf ./build/output"),
    ("C6-unknown-script",
     "./scripts/mystery-tool.sh --plan input.json"),
]

TRANSCRIPT = {"src": str(SRC), "cases": []}


def write_contract_for(home: Path, project: Path) -> Path:
    sys.path.insert(0, str(SRC / "scripts" / "kb"))
    os.environ["SULDE_HOME"] = str(home)
    import importlib
    import intent_guardian_parts.state as state
    importlib.reload(state)
    contract = state.default_contract(
        intent_id="command-effect-probe",
        objective="probe command effect classification through the real hook chain",
        acceptance_criteria=["classification observable"],
        workspace=project,
        mode="enforce",
        allowed_paths=[str(project)],
        confirmed_by="probe",
    )
    contract["permissions"]["external_write"] = EXTERNAL_WRITE_PERM
    contract["permissions"]["destructive"] = "deny"
    path = state.active_contract_path(home / "data" / "kb", project)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.write_contract(path, contract)
    sys.path.pop(0)
    return path


def run_case(project: Path, home: Path, name: str, command: str) -> dict:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(project),
        "session_id": f"probe-{name}",
        "client": "claude",
    }
    env = os.environ.copy()
    env.update({
        "SULDE_HOME": str(home),
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    proc = subprocess.run(
        [sys.executable, str(ENTRY)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(project), env=env, timeout=30, check=False,
    )
    sys.path.insert(0, str(SRC / "scripts" / "kb"))
    import intent_guardian_parts.state as state
    contract_path = state.active_contract_path(home / "data" / "kb", project)
    sys.path.pop(0)
    events_path = state.audit_path(contract_path)
    events = []
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append({
                "effect": row.get("effect"),
                "reason_code": row.get("reason_code"),
                "session_id": row.get("session_id"),
                "command": (row.get("command") or row.get("target") or "")[:120],
            })
    # durable contract runtime (debt / pending verifications)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    runtime = contract.get("runtime") or {}
    durable = {
        "pending_verifications": runtime.get("pending_verifications"),
        "open_events": runtime.get("open_events"),
        "verified_effects": runtime.get("verified_effects"),
        "authorized_events": runtime.get("authorized_events"),
        "material_sequence": runtime.get("material_sequence"),
        "sequence": runtime.get("sequence"),
    }
    TRANSCRIPT.setdefault("external_write_perm", EXTERNAL_WRITE_PERM)
    return {
        "name": name,
        "command": command,
        "exit": proc.returncode,
        "stdout": proc.stdout.strip()[:2000],
        "stderr": proc.stderr.strip()[:500],
        "denied": "permissionDecision" in proc.stdout and '"deny"' in proc.stdout,
        "ledger_events": events,
        "contract_runtime": durable,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ce-probe-", suffix=str(os.getpid())) as tmp:
        tmp = Path(tmp)
        project = tmp / "proj"
        project.mkdir()
        (project / ".sulde-config.yaml").write_text(
            "enabled: true\nrole: coordinator\ndocs_hub: ./docs-hub\nfrontends: []\n"
            "enforcement_level: balanced\nenforcement_grace_period_days: 7\nlang: en\n",
            encoding="utf-8",
        )
        home = tmp / "sulde-home"
        (home / "data" / "kb").mkdir(parents=True)
        contract_path = write_contract_for(home, project)
        TRANSCRIPT["project"] = str(project)
        TRANSCRIPT["sulde_home"] = str(home)
        TRANSCRIPT["contract"] = str(contract_path)
        for name, command in CASES:
            record = run_case(project, home, name, command)
            TRANSCRIPT["cases"].append(record)
            verdict = "DENY" if record["denied"] else "silent"
            effects = sorted({e["effect"] for e in record["ledger_events"] if e["effect"]})
            print(f"{name}: exit={record['exit']} hook={verdict} ledger_effects={effects}",
                  file=sys.stderr)
    OUT.write_text(json.dumps(TRANSCRIPT, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"transcript: {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
