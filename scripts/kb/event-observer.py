#!/usr/bin/env python3
"""Inspect Sulde domain logs through one redacted, read-only event contract."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from event_observer import (
    CORRELATION_KEYS,
    DOMAINS,
    EventContractError,
    collect_snapshot,
)
from observation_privacy import (
    ObservationPrivacyError,
    export_approved,
    load_export_proposal,
    load_policy,
    prepare_export,
    privacy_envelope,
    set_mode,
)


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def _correlations(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        key, separator, identifier = value.partition("=")
        if not separator or key not in CORRELATION_KEYS or not identifier.strip():
            expected = ", ".join(sorted(CORRELATION_KEYS))
            raise EventContractError(
                f"--correlate must be KEY=VALUE where KEY is one of: {expected}"
            )
        result[key] = identifier.strip()
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "summary",
            "events",
            "verify",
            "privacy",
            "set-privacy",
            "prepare-export",
            "export",
        ),
    )
    parser.add_argument("--home", type=Path, default=kb_home())
    parser.add_argument("--workspace", type=Path, action="append", default=[])
    parser.add_argument("--domain", choices=sorted(DOMAINS), action="append", default=[])
    parser.add_argument(
        "--provider",
        choices=("claude", "codex", "import", "system", "unknown"),
        action="append",
        default=[],
    )
    parser.add_argument("--correlate", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--mode", choices=("local", "approved-export", "disabled"))
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--proposal")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.action == "privacy":
            print(
                json.dumps(
                    privacy_envelope(load_policy(args.home.expanduser())),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.action == "set-privacy":
            if args.mode is None:
                raise ObservationPrivacyError("set-privacy requires --mode")
            policy = set_mode(args.home.expanduser(), args.mode)
            print(
                json.dumps(
                    privacy_envelope(policy),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0

        correlations = _correlations(args.correlate)
        if args.action == "export":
            if args.contract is None or not args.proposal:
                raise ObservationPrivacyError("export requires --contract and --proposal")
            load_export_proposal(args.home.expanduser(), args.proposal)
            result = export_approved(
                args.home.expanduser(),
                args.contract.expanduser(),
                args.proposal,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0

        snapshot = collect_snapshot(
            args.home.expanduser(),
            workspaces=args.workspace,
            domains=args.domain,
            providers=args.provider,
            correlations=correlations,
            limit=args.limit,
            include_events=args.action in {"events", "prepare-export"},
        )
        if args.action == "prepare-export":
            if args.contract is None or args.output is None:
                raise ObservationPrivacyError(
                    "prepare-export requires --contract and --output"
                )
            card = prepare_export(
                args.home.expanduser(),
                args.contract.expanduser(),
                output=args.output,
                snapshot=snapshot,
                workspaces=args.workspace,
                domains=args.domain,
                providers=args.provider,
                correlations=correlations,
                limit=args.limit,
            )
            print(json.dumps(card, ensure_ascii=False, sort_keys=True))
            return 0
    except (EventContractError, ObservationPrivacyError, OSError, UnicodeError) as error:
        print(f"ERROR event-observer: {error}", file=sys.stderr)
        return 2

    if args.action == "summary":
        payload = {
            "schema": snapshot["schema"],
            "stateVersion": snapshot["stateVersion"],
            "asOfSeq": snapshot["asOfSeq"],
            "sourceRevision": snapshot["sourceRevision"],
            "generated_at": snapshot["generated_at"],
            "read_only": snapshot["read_only"],
            "authoritative_sources_unchanged": snapshot[
                "authoritative_sources_unchanged"
            ],
            "privacy": snapshot["privacy"],
            "projectionCache": snapshot["projectionCache"],
            "summary": snapshot["summary"],
        }
    else:
        payload = snapshot
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if args.action == "verify":
        if snapshot["summary"]["contract_healthy"] is False:
            return 1
        if snapshot["summary"]["contract_healthy"] is not True:
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
