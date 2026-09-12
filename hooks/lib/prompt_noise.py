"""Shared structural noise gates for capture and recall entry points."""

from __future__ import annotations

import re
from typing import Any


MIN_CONTENT_CHARS = 20
MAX_RECALL_QUERY_CHARS = 2000
RECALL_QUERY_TAIL_CHARS = 800
IMAGE_PLACEHOLDER_RE = re.compile(r"(?:\[Image #\d+\]\s*)+")
SYSTEM_NOTIFICATION_MARKER = "[system notification - not user input]"
SYSTEM_PROMPT_HEADER_RE = re.compile(
    # 角色名不穷举：用“你是 <角色> + 输出契约”识别后续新增的 headless 器官。
    r"\A你是\s*\S.{0,60}?[。，,：:\s].{0,400}?"
    r"(?:只输出|必须只输出|严格包含|契约严格为|字段严格为|不执行任何写库)",
    re.IGNORECASE | re.DOTALL,
)
DELEGATED_TASK_HEADER_RE = re.compile(
    # Harness-generated subagent tasks are operational envelopes, not user recall intent.
    # Keep this structural so new skills do not require another hard-coded name.
    r"\A严格按照\s+[^\s]{1,80}\s+定义.{0,240}?"
    r"(?:不要创建|不创建|禁止创建)子代理.{0,1200}?"
    r"Project\s+root\s*:",
    re.IGNORECASE | re.DOTALL,
)
JSON_CONTRACT_RE = re.compile(r"\{\s*[\"“][^\"”\n]{1,80}[\"”]\s*:")
MACHINE_PAYLOAD_RE = re.compile(
    r"(?:待蒸馏窗口|候选原文|指标(?:全景|紧凑摘要)|两路判重命中|"
    r"以下是\s+[^\n]{1,100}原文真源)[：:]"
)
OUTPUT_CONTRACT_MARKERS = (
    "只输出一个 JSON",
    "只输出裸 JSON",
    "顶层必须且只能包含",
    "字段必须严格为",
    "字段严格为",
    "契约严格为",
)
# 只拦没有业务问题、仅用于测量检索通道的合成探针；真实的延迟诊断问题必须放行。
RECALL_PROBE_RE = re.compile(
    r"\A(?:随便|任意)(?:用|给|选)?(?:一个|一条|条)?"
    r"(?:查询|问题|关键词).{0,8}(?:测|测试)(?:一下)?"
    r"(?:检索|召回)?(?:(?:延迟|耗时|性能)(?:基线)?|基线)[？?。！!]?\Z",
    re.IGNORECASE,
)


def is_system_prompt(content: Any) -> bool:
    normalized = str(content).strip()
    lowered = normalized.lower()
    return bool(
        SYSTEM_PROMPT_HEADER_RE.search(normalized)
        or DELEGATED_TASK_HEADER_RE.search(normalized)
        or (
            any(marker.lower() in lowered for marker in OUTPUT_CONTRACT_MARKERS)
            and JSON_CONTRACT_RE.search(normalized)
            and MACHINE_PAYLOAD_RE.search(normalized)
        )
    )


def is_recall_probe(content: Any) -> bool:
    return bool(RECALL_PROBE_RE.fullmatch(str(content).strip()))


def is_recall_noise(content: Any) -> bool:
    """Return whether a query has no user recall intent."""
    return is_system_prompt(content) or is_recall_probe(content)


def bounded_recall_query(content: Any) -> str:
    """Bound subprocess/tokenization cost while retaining questions at either end."""
    query = str(content)
    if len(query) <= MAX_RECALL_QUERY_CHARS:
        return query
    head_chars = MAX_RECALL_QUERY_CHARS - RECALL_QUERY_TAIL_CHARS - 1
    return query[:head_chars] + "\n" + query[-RECALL_QUERY_TAIL_CHARS:]


def noise_category(content: Any, role: str | None = None) -> str | None:
    """Return one exclusive category shared by capture and pruning."""
    normalized = str(content).strip()
    lowered = normalized.lower()
    if lowered.startswith("<task-notification>") or SYSTEM_NOTIFICATION_MARKER in lowered:
        return "notification"
    if IMAGE_PLACEHOLDER_RE.fullmatch(normalized):
        return "image_placeholder"
    if is_system_prompt(normalized):
        return "system_prompt"
    if role != "summary" and len(normalized) < MIN_CONTENT_CHARS:
        return "short"
    return None


def is_noise_content(content: Any, role: str | None = None) -> bool:
    return noise_category(content, role) is not None
