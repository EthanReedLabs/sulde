"""Persist scoped isolated-test evidence without touching production data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".sulde/data/guardian-memory-consistency"


def source_digest(root: Path = ROOT, *, semantic: bool = False) -> str:
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root
    ).decode().split("\0")
    digest = hashlib.sha256()
    for name in sorted(set(paths)):
        if not name or name.startswith((".sulde/", ".codex-agent/", ".ua/")):
            continue
        if semantic and name in {"docs/guardian-memory-consistency/REPORT.md", "docs/guardian-memory-consistency/EVIDENCE.json"}:
            continue
        path = root / name
        if path.is_symlink():
            content = os.readlink(path).encode()
            mode = b"link"
        elif path.is_file():
            content = path.read_bytes()
            mode = b"exec" if path.stat().st_mode & 0o111 else b"file"
        else:
            continue
        digest.update(name.encode() + b"\0" + mode + b"\0" + hashlib.sha256(content).digest())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    allowed_baseline = ROOT.parent / "guardian-v3-dev-merge"
    if source_root not in (ROOT, allowed_baseline):
        parser.error("source root must be this task or its read-only dev baseline")
    if not args.label.replace("-", "").replace("_", "").isalnum():
        parser.error("label must be alphanumeric")
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run = OUT / f"{stamp}-{args.label}"
    run.mkdir()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                       SULDE_AUDIT_CURSOR_HOME=str(OUT / "audit-cursors"))
    command = [sys.executable, "-B", "scripts/kb/run-isolated-tests.py", *args.tests]
    before = source_digest(source_root)
    semantic_before = source_digest(source_root, semantic=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source_root, text=True, encoding="utf-8", errors="strict").strip()
    started = time.monotonic()
    # Git fixtures must not inherit this task repository through TMPDIR.
    with tempfile.TemporaryDirectory(prefix="sulde-memory-consistency-", dir="/private/tmp") as temporary:
        environment["TMPDIR"] = temporary
        with (run / "output.log").open("xb") as output:
            result = subprocess.run(command, cwd=source_root, env=environment, stdout=output,
                                    stderr=subprocess.STDOUT, check=False)
    record = {"schema": "guardian-memory-checks-v1", "label": args.label, "head": head,
              "source_root_role": "task" if source_root == ROOT else "baseline",
              "source_sha256_before": before, "source_sha256_after": source_digest(source_root),
              "semantic_source_sha256_before": semantic_before,
              "semantic_source_sha256_after": source_digest(source_root, semantic=True),
              "command": command, "python": sys.version, "platform": platform.platform(),
              "started_at": stamp, "duration_seconds": time.monotonic() - started,
              "exit_code": result.returncode, "evidence_tier": "isolated_regression",
              "log_sha256": hashlib.sha256((run / "output.log").read_bytes()).hexdigest()}
    record["reusable_success"] = result.returncode == 0 and semantic_before == record["semantic_source_sha256_after"]
    record["semantic_exclusions"] = ["docs/guardian-memory-consistency/REPORT.md", "docs/guardian-memory-consistency/EVIDENCE.json"]
    (run / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": str((run / "result.json").relative_to(ROOT)), **record}, indent=2))
    print("\n".join((run / "output.log").read_text(errors="replace").splitlines()[-25:]))
    return result.returncode if result.returncode else (0 if record["reusable_success"] else 4)


if __name__ == "__main__":
    raise SystemExit(main())
