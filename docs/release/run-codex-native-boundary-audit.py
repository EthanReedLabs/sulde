"""Actual single-seatbelt permission probe, zero provider/model requests.

This is an OS-boundary audit, not a production installation or human approval.
Only the broker's fixed synthetic probe matrix runs. It owns one fresh evidence
directory and disposable descendants; production state and user config are unused.
No outer sandbox wrapper: nesting seatbelt would test initialization interference.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/kb"))
import native_agent_broker as broker
from codex_cli_contract import AUDITED_CODEX_VERSION, codex_probe_spec, successful_version_identity


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / "synthetic-workspace"
    (workspace / ".git").mkdir(parents=True)
    cli = Path(shutil.which("codex")).resolve(strict=True)
    probe = codex_probe_spec(os.environ)
    observed = subprocess.run([str(cli), "--version"], input=probe.stdin,
                              env=probe.environment, capture_output=True, text=True, timeout=10)
    if successful_version_identity(observed.returncode, observed.stdout) != AUDITED_CODEX_VERSION:
        raise RuntimeError("real CLI changed before boundary audit")
    # Synthetic envelope binds actual source/CLI/profile bytes, not installed
    # deployment authority. The separate staged-runtime audit covers that layer.
    frozen = {
        "task_id": "codex-01600-os-boundary",
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "task_definition_sha256": digest(b"synthetic permission boundary task"),
        "brief_sha256": digest(Path(__file__).read_bytes()),
        "worktree_canonical_path": str(workspace),
        "git_common_dir_canonical_path": str(workspace / ".git"),
        "owned_paths": ["owned-existing", "owned-new"],
        "report_relative_path": "synthetic-report.md", "model_reasoning_effort": "high",
        "codex_executable": str(cli), "codex_version": AUDITED_CODEX_VERSION,
        "codex_executable_sha256": digest(cli.read_bytes()),
        "broker_generation": 1, "broker_sha256": digest(Path(broker.__file__).read_bytes()),
        "provider_generation": 1, "permission_profile_name": "sulde-owned-paths",
        "permission_profile_bytes_sha256": digest(broker.permission_profile_bytes(
            ["owned-existing", "owned-new"], worktree=str(workspace))),
        "permission_profile_spec_sha256": digest(b"synthetic OS-boundary scope; no installed authority"),
        "installed_descriptor_sha256": digest(b"synthetic descriptor; not production authority"),
        "runtime_generation": "codex-01600:synthetic-boundary-audit",
        "runtime_tree_sha256": digest(b"candidate OS probe; not installed tree"),
        "agent_runtime_sha256": digest((ROOT / "scripts/kb/agent-runtime.py").read_bytes()),
        "nonce": digest(os.urandom(32)),
    }
    evidence = broker.execute_native_profile_probe(
        broker.build_request(frozen), frozen, evidence_path=str(output / "native-evidence.json"))
    assert evidence["observed_denial"] and evidence["execution_prevented"]
    assert not evidence["policy_pause"] and evidence["probe_receipt"]
    rows = evidence["probe_receipt"]["probes"]
    allowed = [r["probe_id"] for r in rows if not r["execution_prevented"]]
    assert set(allowed) == {"existing_owned_write", "new_owned_create"}
    assert all(r["observed_denial"] for r in rows if r["probe_id"] not in allowed)
    result = {"version": observed.stdout.strip(), "probe_count": len(rows),
              "allowed": allowed, "prevented": len(rows) - len(allowed),
              "real_os_boundary": True, "installed_authority_claimed": False,
              "model_calls": 0, "evidence_sha256": digest((output / "native-evidence.json").read_bytes()),
              "source_sha256": frozen["broker_sha256"], "runner_sha256": digest(Path(__file__).read_bytes())}
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
