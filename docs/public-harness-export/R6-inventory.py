"""Read-only candidate review inventory; emits no authority or raw secret values."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/release"))
from export_public_harness import review_content, verify_tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    candidate = args.candidate.resolve(strict=True)
    plan = json.loads((candidate / "review.json").read_bytes())
    verify_tree(candidate / "tree", plan)
    paths = {row["path"] for row in plan["files"]}
    source_paths = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", "-z", plan["source_revision"]]
    ).decode().split("\0")
    source_modules = {Path(path).stem for path in source_paths if path.endswith(".py")}
    local_modules = {Path(path).stem for path in paths if path.endswith(".py")}
    local_modules.update(Path(path).parent.name for path in paths if path.endswith("/__init__.py"))
    local_modules.update(path.split("/")[0] for path in paths if "/" in path and path.endswith(".py"))
    external = Counter()
    missing_local = []
    missing_literal_docs = []
    scanner_findings = []
    identity_review = []
    python_files = 0
    # Review-only leads. Names/hashes can be synthetic or public; matches never
    # automatically become privacy defects. Do not print matched raw values.
    identity = re.compile(
        r"\b(?:eric|MacMini|MacStudio)\b|\b(?:192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"
        r"|\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
        r"|\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
    for path in sorted(paths):
        raw = (candidate / "tree" / path).read_bytes()
        text = raw.decode("utf-8")
        scanner_findings.extend(review_content(path, raw))
        for number, line in enumerate(text.splitlines(), 1):
            if identity.search(line):
                identity_review.append({"path": path, "line": number,
                                        "line_sha256": hashlib.sha256(line.encode()).hexdigest()})
        if path.endswith(".py"):
            python_files += 1
            for node in ast.walk(ast.parse(text, filename=path)):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                    names = [node.module.split(".")[0]]
                else:
                    continue
                for name in names:
                    if name in sys.stdlib_module_names or name in local_modules:
                        continue
                    if name in source_modules:
                        missing_local.append({"path": path, "line": node.lineno, "module": name})
                    else:
                        external[name] += 1
        if path.endswith(".md"):
            for number, line in enumerate(text.splitlines(), 1):
                for match in re.finditer(r"`((?:scripts|tools|hooks|skills|templates|spec|docs|knowledge)/[A-Za-z0-9_./-]+\.(?:py|sh|ps1|md|json|txt))`", line):
                    reference = match[1]
                    if reference not in paths:
                        missing_literal_docs.append({"path": path, "line": number, "reference": reference})
    print(json.dumps({
        "schema": "sulde-public-static-review-inventory-v1",
        "manifest_sha256": plan["manifest_sha256"], "source_revision": plan["source_revision"],
        "files_verified": len(paths), "python_files_parsed": python_files,
        "scanner_findings": scanner_findings,
        "missing_local_import_candidates": missing_local,
        "external_import_candidates": dict(sorted(external.items())),
        "missing_literal_document_references": missing_literal_docs,
        "identity_review_leads": identity_review,
        "limitations": ["Static inventory, not dependency execution or complete privacy proof.",
                        "Literal references may describe user-created files; imports may be optional.",
                        "No network, installation, subprocess import, candidate mutation or publication."],
    }, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
