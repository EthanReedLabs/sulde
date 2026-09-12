#!/usr/bin/env python3
"""Build or validate the deterministic knowledge corpus manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))

from common import git_tracked_documents
from corpus_manifest import (
    MANIFEST_RELATIVE,
    build_manifest,
    load_manifest,
    render_manifest,
    write_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        manifest = load_manifest(ROOT, verify_files=True)
        print(f"knowledge/MANIFEST.json verified: {manifest.document_count} documents")
        return 0
    manifest = build_manifest(ROOT, git_tracked_documents(ROOT))
    rendered = render_manifest(manifest)
    output = ROOT / MANIFEST_RELATIVE
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            print(
                "knowledge/MANIFEST.json is stale; rerun python scripts/kb/build-corpus-manifest.py"
            )
            return 1
        print(f"knowledge/MANIFEST.json is current: {manifest.document_count} documents")
        return 0
    write_manifest(ROOT, manifest)
    print(f"generated knowledge/MANIFEST.json: {manifest.document_count} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
