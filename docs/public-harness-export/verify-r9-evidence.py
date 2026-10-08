"""Independently reread R9 candidate facts; never execute a Hook or promote."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/release"))
from export_public_harness import verify_tree


def read(path):
    return json.loads(path.read_bytes())


def seal(payload, field):
    unsigned = {key: value for key, value in payload.items() if key != field}
    digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    assert payload[field] == digest, field


def main():
    base = ROOT / ".sulde/public-export"
    old, new = read(base / "review-011/review.json"), read(base / "review-012/review.json")
    verify_tree(base / "review-012/tree", new)
    previous = {row["path"]: row for row in old["files"]}
    current = {row["path"]: row for row in new["files"]}
    assert previous.keys() == current.keys()
    changed = sorted(path for path in current if previous[path] != current[path])
    assert len(changed) == 8
    assert old["findings"] == new["findings"]
    for finding in new["findings"]:
        path, line = finding["path"], finding["line"] - 1
        left = (base / "review-011/tree" / path).read_text().splitlines()[line]
        right = (base / "review-012/tree" / path).read_text().splitlines()[line]
        assert left == right
    checkout = base / "validation-012/checkout"
    for relative, entry in current.items():
        path = checkout / relative
        assert not path.is_symlink() and path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        assert ("100755" if path.stat().st_mode & 0o111 else "100644") == entry["mode"]
    assert not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=checkout)
    slot = base / "r9-candidate-001/candidates/r9-public"
    state, receipt = read(slot / "state.json"), read(slot / "verification-receipt.json")
    seal(state, "state_sha256")
    seal(receipt, "receipt_sha256")
    assert state["status"] == receipt["status"] == "verified"
    assert state["receipt_sha256"] == receipt["receipt_sha256"]
    assert receipt["source"] == state["source"]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    assert commit == receipt["source"]["commit"]
    proof = receipt["verifications"]["preexecution_chain"]
    intent = slot / "isolated/sulde-home/data/kb/intent/workspaces"
    events = []
    contracts = []
    for path in intent.glob("*.events.jsonl"):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            event = row.get("event", row)
            if event.get("event_id") == proof["started_event_id"]:
                events.append(event)
                contracts.append(path.with_name(path.name.replace(".events.jsonl", ".json")))
    assert len(events) == 1
    event = events[0]
    for key in ("session_id", "loaded_module_generation", "artifact_generation"):
        assert event[key] == proof[key], key
    assert event["call_id"] == proof["started_call_id"] == "candidate_native_2"
    assert event["phase"] == "started" and event["supervision_status"] == "live_verified"
    assert proof["destructive_pre_denied"] and proof["positive_executed"] and proof["outside_plan_write_executed"]
    target = Path(event["target"])
    contract = read(contracts[0])
    probe = contract["runtime"]["pre_execution_probe"]
    saved = [row for row in contract["runtime"]["pre_execution_proofs"] if row["proof_id"] == proof["proof_id"]]
    assert len(saved) == 1 and saved[0]["target"] == str(target) == probe["target"]
    assert target.parent == Path("/private/tmp")
    assert target.name == "sulde-pre-execution-canary-" + proof["probe_id"]
    assert probe["command"] == "rm -- " + str(target)
    assert not os.path.lexists(target)
    assert proof["artifact_generation"] == receipt["artifact"]["generation"]
    assert proof["external_model_requests"] == 0
    assert receipt["verifications"]["native_permission_ui"]["status"] == "unobserved"
    assert receipt["verifications"]["scheduler_host"]["status"] == "unobserved"
    result = {"status": "verified", "manifest_sha256": new["manifest_sha256"],
              "files": len(current), "changed_files": changed, "retained_findings_unchanged": True,
              "receipt_sha256": receipt["receipt_sha256"], "native_proof_id": proof["proof_id"],
              "event_id": event["event_id"], "dual_generation_match": True, "marker_absent_after_finalize": True,
              "canary": "precreated marker; rm pre-denied; finalize verifies retained bytes and removes marker",
              "public_checkout_clean": True, "production_install_performed": False}
    output = base / "r9-independent-readback.json"
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
