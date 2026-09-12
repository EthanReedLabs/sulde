#!/usr/bin/env python3
"""Plan and quarantine explicitly declared, settled derived details only.

This dedicated store is never an authoritative ledger or a general file cleaner.
No deletion, implicit root, scheduler invocation, or production permission.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

SCHEMA = "derived-detail-quarantine-v1"
MAX_MANIFESTS = 4096


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def content(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("unsafe or oversized detail")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def root_path(root):
    root = Path(root).absolute()
    if root.is_symlink() or root.resolve() != root or not root.is_dir():
        raise ValueError("explicit canonical nonsymlink store required")
    return root


def plan(root, *, source_version, generator_version, ttl_seconds, capacity, at=None):
    root = root_path(root)
    if not source_version or not generator_version or not 1 <= ttl_seconds <= 366 * 86400 or not 1 <= capacity <= MAX_MANIFESTS:
        raise ValueError("versions, bounded TTL and capacity required")
    at = at or datetime.now(timezone.utc).isoformat()
    current = datetime.fromisoformat(at).timestamp()
    eligible, protected = [], 0
    manifests = []
    for manifest in root.glob("*.meta.json"):
        manifests.append(manifest)
        if len(manifests) > MAX_MANIFESTS:
            raise ValueError("manifest scan capacity exceeded")
    for manifest in sorted(manifests):
        try:
            meta_digest = content(manifest)
            meta = json.loads(manifest.read_text(encoding="utf-8"))
            name = manifest.name.removesuffix(".meta.json")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name):
                raise ValueError("unsafe name")
            if (meta.get("kind") != "derived_detail" or meta.get("authoritative") is not False
                    or meta.get("issue_status") != "closed" or meta.get("effect_status") != "settled"
                    or meta.get("candidate_pending") is not False or meta.get("verified_aggregate") is not False
                    or meta.get("sourceVersion") != source_version or meta.get("generatorVersion") != generator_version):
                raise ValueError("protected or unbound detail")
            target = root / (name + ".detail.json")
            file_digest = content(target)
            if file_digest != meta["sha256"]:
                raise ValueError("detail drift")
            created = datetime.fromisoformat(meta["created_at"])
            if created.tzinfo is None or created.timestamp() > current:
                raise ValueError("invalid timestamp")
            eligible.append({"file": target.name, "manifest": manifest.name, "sha256": file_digest,
                             "manifest_sha256": meta_digest, "created_at": meta["created_at"]})
        except (OSError, ValueError, KeyError, TypeError):
            protected += 1
    eligible.sort(key=lambda row: (row["created_at"], row["file"]))
    excess = max(0, len(eligible) - capacity)
    selected = [row for i, row in enumerate(eligible)
                if i < excess or current - datetime.fromisoformat(row["created_at"]).timestamp() >= ttl_seconds]
    result = {"schema": SCHEMA, "root": str(root), "sourceVersion": source_version,
              "generatorVersion": generator_version, "ttl_seconds": ttl_seconds, "capacity": capacity,
              "at": at, "candidates": selected, "protected": protected, "status": "dry_run"}
    return {**result, "plan_id": digest(result)}


def readback(root, approved):
    root = root_path(root)
    destination = root / ".quarantine" / approved["plan_id"]
    checked = 0
    for row in approved["candidates"]:
        for name, expected in ((row["file"], row["sha256"]), (row["manifest"], row["manifest_sha256"])):
            if (root / name).exists() or content(destination / name) != expected:
                raise ValueError("quarantine independent readback failed")
            checked += 1
    return {"schema": SCHEMA, "status": "verified", "plan_id": approved["plan_id"], "files_checked": checked, "deletion_performed": False}


def quarantine(root, approved):
    # Recompute every eligibility fact; plan bytes confer no authority.
    current = plan(root, source_version=approved["sourceVersion"], generator_version=approved["generatorVersion"],
                   ttl_seconds=approved["ttl_seconds"], capacity=approved["capacity"], at=approved["at"])
    if current != approved:
        raise ValueError("dry-run drift; review a new plan")
    root = root_path(root)
    area = root / ".quarantine"
    if area.is_symlink():
        raise ValueError("unsafe quarantine")
    area.mkdir(exist_ok=True, mode=0o700)
    destination = area / approved["plan_id"]
    destination.mkdir(mode=0o700)
    for row in approved["candidates"]:
        # Recheck immediately before each reversible move.
        for name, expected in ((row["file"], row["sha256"]), (row["manifest"], row["manifest_sha256"])):
            if content(root / name) != expected:
                raise ValueError("detail changed before quarantine")
            os.rename(root / name, destination / name)
    return readback(root, approved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-version")
    parser.add_argument("--generator-version")
    parser.add_argument("--ttl-seconds", type=int, default=30 * 86400)
    parser.add_argument("--capacity", type=int, default=250)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--quarantine-plan", type=Path)
    group.add_argument("--readback-plan", type=Path)
    args = parser.parse_args()
    if args.quarantine_plan or args.readback_plan:
        approved = json.loads((args.quarantine_plan or args.readback_plan).read_text(encoding="utf-8"))
        result = (quarantine if args.quarantine_plan else readback)(args.root, approved)
    else:
        result = plan(args.root, source_version=args.source_version, generator_version=args.generator_version,
                      ttl_seconds=args.ttl_seconds, capacity=args.capacity)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
