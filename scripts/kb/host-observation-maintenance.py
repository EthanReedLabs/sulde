#!/usr/bin/env python3
"""Explicit bounded rebuild of derived host evidence; never edits source logs."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from host_capabilities import _assert_test_write_isolated, _read_provenance_key, _valid_observation
from host_observation_index import rebuild_step


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--provider", choices=("codex", "claude"), required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--max-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--recover-current-transition", action="store_true")
    parser.add_argument("--recover-history", action="store_true")
    args = parser.parse_args()
    _assert_test_write_isolated(args.home, explicit_home=True)
    try:
        result = rebuild_step(
            args.home, args.provider, args.session_id,
            key=_read_provenance_key(args.home),
            validate=lambda row: _valid_observation(row, args.home), max_bytes=args.max_bytes,
        )
        if (args.recover_current_transition or args.recover_history) and result["status"] == "complete":
            from session_lifecycle_lineage import recover_current_transition
            result["workspace_lineage"] = recover_current_transition(
                args.home, provider=args.provider, session_id=args.session_id,
            )
        if args.recover_history and result["status"] == "complete":
            from session_lifecycle_history import recover_history
            result["historical_lineage"] = recover_history(
                args.home, provider=args.provider, session_id=args.session_id)
            if result["historical_lineage"]["status"] == "inconclusive":
                result["status"] = "inconclusive"
    except (OSError, ValueError, RuntimeError) as error:
        result = {"status": "inconclusive", "error_kind": type(error).__name__,
                  "source_modified": False, "authority_transferred": False}
    print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] == "inconclusive" else 0


if __name__ == "__main__":
    raise SystemExit(main())
