#!/usr/bin/env python3
"""Render provider-native interactive dispatch instructions for a Sulde task."""

from __future__ import annotations

import argparse
import json
import sys

from runtime_provider import (
    CAPABILITY_TIERS,
    CODEX_REASONING_LEVELS,
    ProviderError,
    model_dispatch_plan,
    render_dispatch_instructions,
)


def configure_utf8_stdio() -> None:
    """Keep machine-readable output UTF-8 when Windows redirects the streams."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("claude", "codex"), required=True)
    parser.add_argument("--tier", choices=CAPABILITY_TIERS, required=True)
    parser.add_argument("--current-model")
    parser.add_argument("--current-tier", choices=CAPABILITY_TIERS)
    parser.add_argument("--current-effort", choices=CODEX_REASONING_LEVELS)
    parser.add_argument("--required-effort", choices=CODEX_REASONING_LEVELS)
    parser.add_argument("--model-advice", action="store_true",
                        help="include model/reasoning advice only when the user explicitly requests it")
    parser.add_argument("--task", required=True)
    parser.add_argument("--fresh-session", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser.parse_args()


def main() -> int:
    configure_utf8_stdio()
    args = parse_args()
    try:
        plan = model_dispatch_plan(
            args.provider,
            args.tier,
            current_model=args.current_model,
            current_capability_tier=args.current_tier,
            current_effort=args.current_effort,
            required_effort=args.required_effort,
            model_advice=args.model_advice,
        )
        instructions = render_dispatch_instructions(
            plan,
            task_path=args.task,
            fresh_session=args.fresh_session,
        )
    except ProviderError as error:
        print(f"SULDE MODEL DISPATCH: FAIL: {error}", file=sys.stderr)
        return 2
    payload = {**plan, "instructions": instructions}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print("\n".join(instructions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
