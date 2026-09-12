"""Parse legacy control-shaped messages without treating text as authority."""

from __future__ import annotations

from dataclasses import dataclass
import re


EVENT_APPROVAL_PATTERN = re.compile(
    r"(?i)^\s*(?:批准\s*事件|approve\s+event)\s*[:：#]?\s*([0-9a-f]{64})\s*[。.!]?\s*$"
)
PROPOSAL_APPROVAL_PATTERN = re.compile(
    r"(?i)^\s*(?:批准\s*意图提案|approve\s+intent\s+proposal)\s*[:：#]?\s*"
    r"([0-9a-f]{64})\s*[。.!]?\s*$"
)
CURRENT_PROPOSAL_APPROVAL_PATTERN = re.compile(
    r"(?i)^\s*(?:(?:批准|同意|确认)(?:\s*当前)?(?:\s*意图)?(?:\s*方案|\s*提案)"
    r"|approve\s+(?:the\s+)?current\s+(?:intent\s+)?proposal)\s*[。.!]?\s*$"
)
CURRENT_PROPOSAL_REJECTION_PATTERN = re.compile(
    r"(?i)^\s*(?:(?:拒绝|驳回)(?:\s*当前)?(?:\s*意图)?(?:\s*方案|\s*提案)"
    r"|reject\s+(?:the\s+)?current\s+(?:intent\s+)?proposal)\s*[。.!]?\s*$"
)
CURRENT_OBSERVATION_EXPORT_APPROVAL_PATTERN = re.compile(
    r"(?i)^\s*(?:批准(?:\s*当前)?\s*观察导出"
    r"|approve\s+(?:the\s+)?current\s+observation\s+export)\s*[。.!]?\s*$"
)
CURRENT_OBSERVATION_EXPORT_REJECTION_PATTERN = re.compile(
    r"(?i)^\s*(?:拒绝(?:\s*当前)?\s*观察导出"
    r"|reject\s+(?:the\s+)?current\s+observation\s+export)\s*[。.!]?\s*$"
)
CURRENT_INTENT_CONFIRMATION_PATTERN = re.compile(
    r"(?i)^\s*(?:确认(?:\s*当前)?\s*意图(?:\s*镜像)?"
    r"|confirm\s+(?:the\s+)?current\s+intent)\s*[。.!]?\s*$"
)
CURRENT_INTENT_REJECTION_PATTERN = re.compile(
    r"(?i)^\s*(?:拒绝(?:\s*当前)?\s*意图(?:\s*镜像)?"
    r"|reject\s+(?:the\s+)?current\s+intent)\s*[。.!]?\s*$"
)
EXPLICIT_PAUSE_PATTERNS = (
    r"^\s*(?:先|立即)?暂停(?:修改|执行|操作)?\s*[。.!]?\s*$",
    r"^\s*(?:先)?停止(?:修改|执行|操作)\s*[。.!]?\s*$",
    r"^\s*先别(?:改|动|继续)\s*[。.!]?\s*$",
    r"^\s*stop (?:editing|changing|executing)\s*[.!]?\s*$",
)
EXPLICIT_RESUME_PATTERNS = (
    r"^\s*确认(?:当前)?意图(?:镜像)?并恢复",
    r"^\s*resume (?:the )?intent contract",
)
INTERVENTION_SUCCESS_PATTERN = re.compile(
    r"(?i)^\s*(?:确认(?:\s*当前)?\s*外部操作成功|confirm\s+(?:the\s+)?external\s+action\s+succeeded)"
    r"\s*[:：]\s*(\S(?:[\s\S]*\S)?)\s*$"
)
INTERVENTION_FAILURE_PATTERN = re.compile(
    r"(?i)^\s*(?:确认(?:\s*当前)?\s*外部操作失败|confirm\s+(?:the\s+)?external\s+action\s+failed)"
    r"\s*[:：]\s*(\S(?:[\s\S]*\S)?)\s*$"
)
INTERVENTION_REPROBE_PATTERN = re.compile(
    r"(?i)^\s*(?:重新检查(?:\s*当前)?\s*外部操作|reprobe\s+(?:the\s+)?external\s+action)\s*[。.!]?\s*$"
)
INTERVENTION_RETRY_PATTERN = re.compile(
    r"(?i)^\s*(?:授权重试(?:\s*当前)?\s*外部操作|authorize\s+(?:one\s+)?external\s+action\s+retry)\s*[。.!]?\s*$"
)
INTERVENTION_ABORT_PATTERN = re.compile(
    r"(?i)^\s*(?:终止(?:\s*当前)?\s*外部操作|abort\s+(?:the\s+)?external\s+action)\s*[。.!]?\s*$"
)


@dataclass(frozen=True)
class HumanControl:
    action: str
    target: str
    decision: str = ""
    evidence: str = ""


_NATIVE_ONLY_ACTIONS = frozenset(
    {
        "approve-proposal",
        "reject-proposal",
        "approve-observation-export",
        "reject-observation-export",
        "confirm-intent",
        "reject-intent",
        "resume",
    }
)
_NATIVE_ONLY_INTERVENTION_DECISIONS = frozenset(
    {"reprobe_authorized", "retry_authorized", "abort"}
)
_RETIRED_NON_BLOCKING_ACTIONS = frozenset(
    {"retired-event-approval", "reject-opaque-proposal-approval"}
)


def text_control_requires_native(control: HumanControl | None) -> bool:
    """Return whether a parsed text choice requires verified native authority.

    Human evidence that an external effect succeeded or failed remains a fact
    attestation. Fixed yes/no/retry/resume controls are authority and therefore
    may not be manufactured through ``UserPromptSubmit`` on any provider.
    """
    if control is None:
        return False
    if control.action in _NATIVE_ONLY_ACTIONS:
        return True
    return bool(
        control.action == "intervention-resolve"
        and control.decision in _NATIVE_ONLY_INTERVENTION_DECISIONS
    )


def codex_text_control_requires_native(control: HumanControl | None) -> bool:
    """Backward-compatible alias for the provider-neutral native boundary."""
    return text_control_requires_native(control)


def text_control_requires_receipt(
    control: HumanControl | None,
    *,
    provider: str,
) -> bool:
    """Return whether a host adapter must fail closed without a text receipt."""
    del provider  # Kept in the API for host-adapter compatibility.
    if control is None or control.action in _RETIRED_NON_BLOCKING_ACTIONS:
        return False
    if text_control_requires_native(control):
        return False
    return True


_CONTROL_SUFFIX_BOUNDARY = re.compile(r"^(?:\s*$|\s*[,，。.!！;；:：\n])")
_CONTRADICTORY_SUFFIX = re.compile(
    r"(?:不要|不准|别|取消|拒绝|仅(?:是)?示例|只是示例|引用|假设|"
    r"do\s+not|don't|cancel|reject|example|quoted)",
    re.IGNORECASE,
)


def _matches_control_prefix(value: str, patterns: tuple[str, ...]) -> bool:
    """Accept an explicit leading control plus harmless explanatory prose.

    The old full-line ceremony rejected natural messages such as
    ``确认意图镜像并恢复，这个误拦截也要修复``.  A control is now valid
    when it is the first utterance, ends at punctuation/whitespace, and the
    suffix does not negate or quote it.  Embedded examples still do not match.
    """
    for pattern in patterns:
        match = re.match(pattern, value, re.IGNORECASE)
        if not match:
            continue
        suffix = value[match.end():]
        if not _CONTROL_SUFFIX_BOUNDARY.match(suffix):
            continue
        if _CONTRADICTORY_SUFFIX.search(suffix):
            continue
        return True
    return False


def parse_human_control(prompt: str) -> HumanControl | None:
    """Return one exact control request; quoted examples and surrounding prose do not match."""
    value = prompt.strip()
    if not value:
        return None
    if match := EVENT_APPROVAL_PATTERN.fullmatch(value):
        return HumanControl("retired-event-approval", match.group(1).lower())
    if CURRENT_PROPOSAL_APPROVAL_PATTERN.fullmatch(value):
        return HumanControl("approve-proposal", "current")
    if CURRENT_PROPOSAL_REJECTION_PATTERN.fullmatch(value):
        return HumanControl("reject-proposal", "current")
    if CURRENT_OBSERVATION_EXPORT_APPROVAL_PATTERN.fullmatch(value):
        return HumanControl("approve-observation-export", "current")
    if CURRENT_OBSERVATION_EXPORT_REJECTION_PATTERN.fullmatch(value):
        return HumanControl("reject-observation-export", "current")
    if CURRENT_INTENT_CONFIRMATION_PATTERN.fullmatch(value):
        return HumanControl("confirm-intent", "current")
    if CURRENT_INTENT_REJECTION_PATTERN.fullmatch(value):
        return HumanControl("reject-intent", "current")
    if match := PROPOSAL_APPROVAL_PATTERN.fullmatch(value):
        return HumanControl("reject-opaque-proposal-approval", match.group(1).lower())
    if any(re.fullmatch(pattern, value, re.IGNORECASE) for pattern in EXPLICIT_PAUSE_PATTERNS):
        return HumanControl("pause", "")
    if _matches_control_prefix(value, EXPLICIT_RESUME_PATTERNS):
        return HumanControl("resume", "")
    if match := INTERVENTION_SUCCESS_PATTERN.fullmatch(value):
        return HumanControl(
            "intervention-resolve",
            "current",
            decision="human_attested_success",
            evidence=match.group(1).strip(),
        )
    if match := INTERVENTION_FAILURE_PATTERN.fullmatch(value):
        return HumanControl(
            "intervention-resolve",
            "current",
            decision="confirmed_failed",
            evidence=match.group(1).strip(),
        )
    if INTERVENTION_REPROBE_PATTERN.fullmatch(value):
        return HumanControl(
            "intervention-resolve",
            "current",
            decision="reprobe_authorized",
            evidence="用户要求只重新检查当前外部效果，不授权重做",
        )
    if INTERVENTION_RETRY_PATTERN.fullmatch(value):
        return HumanControl(
            "intervention-resolve",
            "current",
            decision="retry_authorized",
            evidence="用户授权对同一外部效果进行一次精确重试",
        )
    if INTERVENTION_ABORT_PATTERN.fullmatch(value):
        return HumanControl(
            "intervention-resolve",
            "current",
            decision="abort",
            evidence="用户终止当前外部操作且不授权重试",
        )
    return None
