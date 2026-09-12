#!/usr/bin/env python3
"""Inspect independent problems; explicit aggregation and local verification."""
import argparse
import json
from pathlib import Path
from life_health import aggregate, problem_status, queue_plan, sync_preflight, verify_problem
from sulde_paths import kb_home


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=kb_home())
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--status", action="store_true")
    actions.add_argument("--aggregate", action="store_true")
    actions.add_argument("--queue-plan", action="store_true")
    actions.add_argument("--sync-preflight", action="store_true")
    actions.add_argument("--verify", metavar="FINGERPRINT")
    parser.add_argument("--repair-commit")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.verify:
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not args.repair_commit or not args.source_root:
            parser.error("verification requires repair commit and source root")
        result = verify_problem(args.home, args.verify, command=command, repair_commit=args.repair_commit, source_root=args.source_root)
    else:
        action = aggregate if args.aggregate else queue_plan if args.queue_plan else sync_preflight if args.sync_preflight else problem_status
        result = action(args.home)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
