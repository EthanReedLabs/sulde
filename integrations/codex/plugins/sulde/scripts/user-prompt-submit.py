#!/usr/bin/env python3
"""Adapt the existing Sulde UserPromptSubmit output to the Codex hook schema."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
import os
import re
import subprocess
from types import SimpleNamespace
from typing import Any

from _adapter_common import (
    configure_utf8_stdio,
    normalize_codex_session,
    run_runtime,
    runtime_root,
)


configure_utf8_stdio()

SULDE_HOOK = runtime_root() / "hooks" / "user_prompt_submit.py"


def _text_control_requires_receipt(control) -> bool:
    """Require receipts only for factual attestations and pause requests."""
    if control is None or control.action in {
        "retired-event-approval",
        "reject-opaque-proposal-approval",
    }:
        return False
    if control.action in {
        "approve-proposal",
        "reject-proposal",
        "approve-observation-export",
        "reject-observation-export",
        "confirm-intent",
        "reject-intent",
        "resume",
    }:
        return False
    return not (
        control.action == "intervention-resolve"
        and getattr(control, "decision", "")
        in {"reprobe_authorized", "retry_authorized", "abort"}
    )


def _payload() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    normalize_codex_session(value)
    if "transcript_path" not in value and value.get("transcriptPath"):
        value["transcript_path"] = value["transcriptPath"]
    # The Codex adapter is the authoritative host boundary.  Do not rely on a
    # client field being present (or correctly labelled) in the hook payload.
    value["client"] = "codex"
    value["sulde_observation_source"] = os.environ.get(
        "SULDE_HOOK_OBSERVATION_SOURCE",
        "live_host_hook",
    )
    return value


def _fallback_control_request(prompt: str):
    value = prompt.strip()
    if re.fullmatch(
        r"(?i)(?:拒绝(?:\s*当前)?\s*意图(?:\s*镜像)?"
        r"|reject\s+(?:the\s+)?current\s+intent)\s*[。.!]?",
        value,
    ):
        return SimpleNamespace(action="reject-intent", target="current")
    if re.fullmatch(
        r"(?i)(?:确认(?:\s*当前)?\s*意图(?:\s*镜像)?"
        r"|confirm\s+(?:the\s+)?current\s+intent)\s*[。.!]?",
        value,
    ):
        return SimpleNamespace(action="confirm-intent", target="current")
    if re.fullmatch(
        r"(?i)(?:批准(?:\s*当前)?\s*观察导出"
        r"|approve\s+(?:the\s+)?current\s+observation\s+export)\s*[。.!]?",
        value,
    ):
        return SimpleNamespace(action="approve-observation-export", target="current")
    if re.fullmatch(
        r"(?i)(?:拒绝(?:\s*当前)?\s*观察导出"
        r"|reject\s+(?:the\s+)?current\s+observation\s+export)\s*[。.!]?",
        value,
    ):
        return SimpleNamespace(action="reject-observation-export", target="current")
    if re.fullmatch(
        r"(?i)(?:(?:批准|同意|确认)(?:\s*当前)?(?:\s*意图)?(?:\s*方案|\s*提案)"
        r"|approve\s+(?:the\s+)?current\s+(?:intent\s+)?proposal)\s*[。.!]?",
        value,
    ):
        return SimpleNamespace(action="approve-proposal", target="current")
    if re.fullmatch(
        r"(?i)(?:(?:拒绝|驳回)(?:\s*当前)?(?:\s*意图)?(?:\s*方案|\s*提案)"
        r"|reject\s+(?:the\s+)?current\s+(?:intent\s+)?proposal)\s*[。.!]?",
        value,
    ):
        return SimpleNamespace(action="reject-proposal", target="current")
    patterns = (
        (
            "reject-opaque-proposal-approval",
            r"(?i)(?:批准\s*意图提案|approve\s+intent\s+proposal)\s*[:：#]?\s*"
            r"([0-9a-f]{64})[。.!]?",
        ),
        (
            "retired-event-approval",
            r"(?i)(?:批准\s*事件|approve\s+event)\s*[:：#]?\s*"
            r"([0-9a-f]{64})[。.!]?",
        ),
    )
    for action, pattern in patterns:
        if match := re.fullmatch(pattern, value):
            return SimpleNamespace(action=action, target=match.group(1).lower())
    pause_patterns = (
        r"(?i)(?:先|立即)?暂停(?:修改|执行|操作)?\s*[。.!]?",
        r"(?i)(?:先)?停止(?:修改|执行|操作)\s*[。.!]?",
        r"(?i)先别(?:改|动|继续)\s*[。.!]?",
        r"(?i)stop (?:editing|changing|executing)\s*[.!]?",
    )
    if any(re.fullmatch(pattern, value) for pattern in pause_patterns):
        return SimpleNamespace(action="pause", target="")
    resume_patterns = (
        r"(?i)^确认(?:当前)?意图(?:镜像)?并恢复",
        r"(?i)^resume (?:the )?intent contract",
    )
    for pattern in resume_patterns:
        match = re.match(pattern, value)
        if not match:
            continue
        suffix = value[match.end():]
        if not re.match(r"^(?:\s*$|\s*[,，。.!！;；:：\n])", suffix):
            continue
        if re.search(
            r"(?i)(?:不要|不准|别|取消|拒绝|仅(?:是)?示例|只是示例|引用|假设|"
            r"do\s+not|don't|cancel|reject|example|quoted)",
            suffix,
        ):
            continue
        return SimpleNamespace(action="resume", target="")
    for decision, pattern in (
        (
            "human_attested_success",
            r"(?i)(?:确认(?:\s*当前)?\s*外部操作成功|confirm\s+(?:the\s+)?external\s+action\s+succeeded)\s*[:：]\s*(\S(?:.*\S)?)",
        ),
        (
            "confirmed_failed",
            r"(?i)(?:确认(?:\s*当前)?\s*外部操作失败|confirm\s+(?:the\s+)?external\s+action\s+failed)\s*[:：]\s*(\S(?:.*\S)?)",
        ),
    ):
        if match := re.fullmatch(pattern, value):
            return SimpleNamespace(
                action="intervention-resolve",
                target="current",
                decision=decision,
                evidence=match.group(1).strip(),
            )
    for decision, evidence, pattern in (
        (
            "reprobe_authorized",
            "用户要求只重新检查当前外部效果，不授权重做",
            r"(?i)(?:重新检查(?:\s*当前)?\s*外部操作|reprobe\s+(?:the\s+)?external\s+action)\s*[。.!]?",
        ),
        (
            "retry_authorized",
            "用户授权对同一外部效果进行一次精确重试",
            r"(?i)(?:授权重试(?:\s*当前)?\s*外部操作|authorize\s+(?:one\s+)?external\s+action\s+retry)\s*[。.!]?",
        ),
        (
            "abort",
            "用户终止当前外部操作且不授权重试",
            r"(?i)(?:终止(?:\s*当前)?\s*外部操作|abort\s+(?:the\s+)?external\s+action)\s*[。.!]?",
        ),
    ):
        if re.fullmatch(pattern, value):
            return SimpleNamespace(
                action="intervention-resolve",
                target="current",
                decision=decision,
                evidence=evidence,
            )
    return None


def _control_request(prompt: str):
    try:
        kb_scripts = runtime_root() / "scripts" / "kb"
        if str(kb_scripts) not in sys.path:
            sys.path.insert(0, str(kb_scripts))
        from human_control import parse_human_control

        return parse_human_control(prompt)
    except (ImportError, OSError, RuntimeError, SyntaxError):
        # Preserve legacy recognition so authority-shaped text is suppressed
        # from task routing even if the packaged parser cannot be imported.
        return _fallback_control_request(prompt)


def _emit(context: str) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def main() -> int:
    payload = _payload()
    parsed_control = _control_request(str(payload.get("prompt") or ""))
    control = parsed_control if _text_control_requires_receipt(parsed_control) else None
    context = ""
    try:
        completed = run_runtime(
            SULDE_HOOK,
            input_text=json.dumps(payload, ensure_ascii=False),
            timeout=115,
        )
        context = completed.stdout.strip()
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            status = (
                f"[sulde intent] CONTROL_NOT_RECORDED action={control.action} "
                f"target={control.target} reason=runtime_exit_{completed.returncode}"
                if control
                else f"[sulde intent] UNAVAILABLE reason=runtime_exit_{completed.returncode}"
            )
            context = "\n".join(part for part in (context, status) if part)
            _emit(context)
            return 2 if control else 0
    except (OSError, subprocess.TimeoutExpired) as error:
        reason = "timeout" if isinstance(error, subprocess.TimeoutExpired) else "spawn_failed"
        context = (
            f"[sulde intent] CONTROL_NOT_RECORDED action={control.action} "
            f"target={control.target} reason={reason}"
            if control
            else f"[sulde intent] UNAVAILABLE reason={reason}"
        )
        sys.stderr.write(context + "\n")
        _emit(context)
        return 2 if control else 0

    if control:
        if control.target != "current":
            target_pattern = re.escape(control.target) if control.target else r"[^\r\n]*?"
        elif control.action == "intervention-resolve":
            target_pattern = r"int-[0-9a-f]{24}"
        else:
            target_pattern = r"[0-9a-f]{64}"
        receipt_pattern = (
            rf"CONTROL_RECORDED action={re.escape(control.action)} "
            rf"target={target_pattern} receipt=[0-9a-f]{{64}} "
            rf"provider=codex session={re.escape(str(payload.get('session_id') or ''))}(?:\.|\s|$)"
        )
        if re.search(receipt_pattern, context) is None:
            status = (
                f"[sulde intent] CONTROL_NOT_RECORDED action={control.action} "
                f"target={control.target} reason=missing_receipt"
            )
            context = "\n".join(part for part in (context, status) if part)
            sys.stderr.write(status + "\n")
            _emit(context)
            return 2

    if not context:
        context = "[sulde intent] UNAVAILABLE reason=empty_runtime_output"
    _emit(context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
