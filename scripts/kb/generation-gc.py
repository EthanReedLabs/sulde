#!/usr/bin/env python3
"""Diagnostic planner for retired Sulde generation trees (no deletion).

R3-01/R3-02: shared-target reclamation is closed.  This tool is a read-only
diagnostic: it reports, per retired target, whether references exist in the
declared lease scopes and whether the target would otherwise be eligible
(identity, retention).  It never deletes anything and offers no apply path —
complete reference coverage cannot be proven in this architecture, so actual
reclamation stays undelivered.  Declaring more or fewer scopes changes the
diagnostic only; it can never authorize deletion.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generation_guard import (  # noqa: E402
    GenerationGuardError,
    plan_retired_reclamation,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retired-dir", type=Path, required=True,
                        help="retired generation root containing *.retirement.json")
    parser.add_argument("--leases-dir", type=Path, action="append", required=True,
                        help="managed-run lease directory to observe; repeat for "
                             "every scope relevant to the diagnostic")
    parser.add_argument("--retention-hours", type=float, default=168.0,
                        help="retention window used for the eligible diagnostic (default: 168h)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        plan = plan_retired_reclamation(
            args.retired_dir,
            leases_dirs=list(args.leases_dir),
            retention_seconds=max(0.0, args.retention_hours * 3600.0),
        )
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except GenerationGuardError as error:
        print(f"SULDE GENERATION GC: FAIL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
