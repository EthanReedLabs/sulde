"""Archive this task's explicit evidence without overwriting a previous run."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts/release"))
import candidate_codex_plugin as candidate


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace"
    ).strip()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    destination = args.destination.absolute()
    mount = Path("/Volumes/Optimus")
    archive_root = mount / "Sulde/tasks/guardian-unified-plan-20261004/S3"
    if not os.path.ismount(mount):
        raise RuntimeError("Optimus is not mounted; do not create a substitute")
    if destination.parent != archive_root or destination.exists():
        raise RuntimeError("exact new S3 archive directory required")
    if destination.resolve() != destination:
        raise RuntimeError("archive destination must not traverse a symlink")

    failed = ROOT / ".codex-agent/s3-candidates/guardian-s3-20261005-660d5df"
    passed = ROOT / ".tmp/s3-candidates/guardian-s3-20261005-fixture2"
    old = candidate._load_state(failed)
    state = candidate._load_state(passed)
    receipt = candidate._load_sealed(
        passed / "verification-receipt.json", schema=candidate.RECEIPT_SCHEMA,
        field="receipt_sha256",
    )
    assert old["status"] == "verification_failed" and old["live_preserved"] is True
    assert state["status"] == receipt["status"] == "verified"
    assert state["promotion_consumed"] is False
    assert state["receipt_sha256"] == receipt["receipt_sha256"]
    live = candidate.installer.deployment_cas_snapshot(
        candidate.installer.default_kb_home(), receipt["codex"]["executable"]
    )
    assert live == receipt["live_prestate"] == state["prepare_live_observation"]
    assert live == old["prepare_live_observation"] == old["live_prestate"] == old["live_poststate"]
    assert old["artifact"]["plugin_tree_sha256"] == state["artifact"]["plugin_tree_sha256"]
    inputs = ("scripts", "tests", "tools", "hooks", "skills", "integrations", "spec")
    assert not git("diff", "4be6e31", "HEAD", "--", *inputs)
    assert not git("status", "--porcelain")

    sources: dict[str, Path] = {}
    for label, slot in (("failed", failed), ("verified", passed)):
        sources[f"{label}/state.json"] = slot / "state.json"
        if label == "verified":
            sources[f"{label}/verification-receipt.json"] = slot / "verification-receipt.json"
        # Only synthetic candidate control facts, never real production ledgers
        # or model/session logs. Locks and caches are not evidence copies.
        contracts = slot / "isolated/sulde-home/data/kb/intent/workspaces"
        for source in sorted(contracts.glob("*.json*")):
            if source.name.endswith((".json", ".jsonl")) and not source.name.startswith("."):
                sources[f"{label}/control/{source.name}"] = source
    evidence = ROOT.parent / "guardian-unified-s2-20261004/.codex-agent/s2-evidence"
    stem = "formal/20261004T135316.528963-c97dd73b4bb0"
    for suffix, expected in (
        (".json", "f171aeea5c63e9b94f3bb540f1ae911641bfe21c4ae781dda1ee85905afbdb26"),
        (".log", "44df73908b35db161539454b4e67ee91ccd98b7a261257d055a841797c21bbff"),
    ):
        source = evidence / (stem + suffix)
        assert digest(source.read_bytes()) == expected
        sources["s2/" + source.name] = source
    sources["s2/paired-entry-02.json"] = evidence / "paired-entry-02.json"
    for source in sorted(Path(__file__).parent.iterdir()):
        if source.suffix in {".md", ".py"}:
            sources["task/" + source.name] = source

    archive_root.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700)  # exclusive: a repeated run never overwrites
    manifest = {}
    for name, source in sources.items():
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f"not a regular source: {source}")
        data = source.read_bytes()
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open("xb") as stream:
            os.chmod(target, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if target.read_bytes() != data or source.read_bytes() != data:
            raise RuntimeError(f"archive readback/source drift: {name}")
        manifest[name] = {"sha256": digest(data), "bytes": len(data)}
    result = {
        "schema": "sulde-s3-evidence-archive-v1", "status": "verified-scoped",
        "source_head": git("rev-parse", "HEAD"), "dev": git("rev-parse", "dev"),
        "main": git("rev-parse", "main"), "production_unchanged": True,
        "live_prestate": live, "full_tests_rerun": False,
        "receipt_sha256": receipt["receipt_sha256"], "files": manifest,
    }
    data = (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    with (destination / "manifest.json").open("xb") as stream:
        os.chmod(destination / "manifest.json", 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    assert (destination / "manifest.json").read_bytes() == data
    print(json.dumps({"archive": str(destination), "files": len(manifest),
                      "manifest_sha256": digest(data)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
