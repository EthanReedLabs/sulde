"""Read back the bounded R10 repair and artifact equality; never install."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / ".sulde/public-export"
SOURCE = "f21cd5eda55740049c977f31eb79db29324b6df0"
sys.path.insert(0, str(ROOT / "scripts/release"))
from export_public_harness import verify_tree


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    assert root.is_dir() and not root.is_symlink()
    result = {}
    for path in root.rglob("*"):
        assert not path.is_symlink(), str(path)
        if path.is_file():
            result[path.relative_to(root).as_posix()] = (
                sha(path), "100755" if path.stat().st_mode & 0o111 else "100644")
    return result


def main():
    old = read(BASE / "review-012/review.json")
    new = read(BASE / "review-013/review.json")
    verify_tree(BASE / "review-012/tree", old)
    verify_tree(BASE / "review-013/tree", new)
    previous = {row["path"]: row for row in old["files"]}
    current = {row["path"]: row for row in new["files"]}
    assert previous.keys() == current.keys() and len(current) == 628
    changed = sorted(path for path in current if previous[path] != current[path])
    assert changed == ["scripts/release/stage_plugin.py", "tests/test_stage_plugin.py"]
    assert old["findings"] == new["findings"] and len(new["findings"]) == 15
    for finding in new["findings"]:
        path, line = finding["path"], finding["line"] - 1
        assert ((BASE / "review-012/tree" / path).read_text().splitlines()[line]
                == (BASE / "review-013/tree" / path).read_text().splitlines()[line])
    checkout = BASE / "validation-013/checkout"
    for path, row in current.items():
        assert sha(checkout / path) == row["sha256"]
        assert ("100755" if (checkout / path).stat().st_mode & 0o111 else "100644") == row["mode"]
    assert not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=checkout)
    artifact_changes = {}
    for name in ("claude", "codex-posix", "codex-windows"):
        left = inventory(BASE / "validation-012/artifacts" / name)
        right = inventory(BASE / "validation-013/artifacts" / name)
        assert left.keys() == right.keys(), name
        diff = sorted(path for path in right if left[path] != right[path])
        assert diff == (["scripts/release/stage_plugin.py"] if name == "claude" else []), (name, diff)
        artifact_changes[name] = {"files": len(right), "changed": diff}

    stage = runpy.run_path(str(ROOT / "scripts/release/stage_plugin.py"))
    entries = stage["release_entries"](ROOT)
    legacy = {e.path.as_posix() for e in entries if e.path.as_posix() in stage["CLAUDE_FILES"]
              or stage["is_prefixed"](e.path, stage["CLAUDE_PREFIXES"])}
    selected = {e.path.as_posix() for e in entries if stage["is_claude_release_path"](e.path)}
    excluded = sorted(legacy - selected)
    expected = {
        "scripts/release/export_public_harness.py",
        "scripts/release/verify_public_harness_candidate.py",
        "scripts/release/public_harness_overlay/README.md",
        "scripts/release/public_harness_overlay/knowledge/SEDIMENTATION-STANDARD.md",
        "scripts/release/public_harness_overlay/hooks/run-hook.sh",
        "scripts/release/public_harness_overlay/hooks/run-hook.ps1",
    }
    assert set(excluded) == expected and not selected - legacy
    # Source files, including private tooling, remain present and unchanged.
    for path in expected | set(changed):
        committed = subprocess.check_output(["git", "show", SOURCE + ":" + path], cwd=ROOT)
        assert (ROOT / path).read_bytes() == committed, path
    unit = read(BASE / "r10-unit-001/results.json")
    assert unit["status"] == "passed" and unit["detail"]["tests_run"] == 44
    assert unit["detail"]["skipped"] == unit["detail"]["production_write_violations"] == 0
    assert sha(BASE / "r10-unit-001/tests.log") == unit["detail"]["log_sha256"]
    validation = read(BASE / "validation-013/results.json")
    assert validation["all_bounded_probes_passed"] and not validation["release_ready"]
    assert validation["manifest_sha256"] == new["manifest_sha256"]
    assert sum(row.get("tests_run", 0) for row in validation["cases"]) == 39
    for row in validation["cases"]:
        assert row["passed"] and row.get("tests_skipped", 0) == 0
        assert sha(BASE / "validation-013" / (row["name"] + ".log")) == row["log_sha256"]
    result = {
        "status": "verified", "source_commit": SOURCE,
        "manifest_sha256": new["manifest_sha256"], "files": 628,
        "changed_public_files": changed, "artifact_comparison": artifact_changes,
        "private_claude_excluded": excluded, "retained_findings_unchanged": True,
        "unit_results_sha256": sha(BASE / "r10-unit-001/results.json"),
        "candidate_results_sha256": sha(BASE / "validation-013/results.json"),
        "candidate_probe_seconds": round(sum(row["seconds"] for row in validation["cases"]), 3),
        "production_install_performed": False,
        "not_retested": ["native_permission_ui", "scheduler_host", "upgrade_rollback", "Windows_native"],
    }
    output = BASE / "r10-independent-readback.json"
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
