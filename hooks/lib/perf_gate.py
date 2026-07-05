"""perf_gate — UserPromptSubmit reminder hook for performance work.

Any prompt mentioning "slow / jank / lag / 慢 / 卡 / 延迟 / 优化" triggers
a reminder that we never write a perf fix without first running diagnosis.
Pure advisory.
"""

from __future__ import annotations

import re
from typing import Any

from sulde_common import SuldeConfig

DEFAULT_TRIGGERS = (
    "慢", "卡", "卡顿", "延迟", "优化", "提速", "加载慢", "进场慢", "响应慢",
    "jank", "lag", "perf", "performance", "slow",
)

DEFAULT_REMINDER_EN = (
    "Performance keyword detected. Do NOT write a perf fix from intuition. "
    "Run diagnosis first (Profiler / instrumentation / measurements) and "
    "include the evidence in the fix task-md."
)
DEFAULT_REMINDER_ZH = (
    "性能关键词命中。禁止凭印象写 perf fix。先跑诊断"
    "(Profiler / 抓包 / 实测数值),把证据写入 fix task-md。"
)


def run(config: SuldeConfig, payload: dict[str, Any]) -> None:
    prompt = str(payload.get("prompt") or "")
    if not prompt.strip():
        return

    triggers = _override_triggers(config)
    if not triggers:
        return
    pattern = re.compile("|".join(re.escape(t) for t in triggers), re.IGNORECASE)
    if not pattern.search(prompt):
        return

    reminder_en, reminder_zh = _override_reminder(config)
    lang_hint_zh = bool(re.search(r"[一-鿿]", prompt))

    lines = [
        "⚠️ sulde perf-gate triggered",
        "",
        reminder_zh if lang_hint_zh else reminder_en,
        "",
        "Docs: docs-hub/00_shared-rules/perf-diagnosis.md (gating rules + tools per stack)",
    ]
    print("\n".join(lines))


def _override_triggers(config: SuldeConfig) -> tuple[str, ...]:
    raw = config.raw.get("enforcement", {}) if isinstance(config.raw, dict) else {}
    perf_cfg = (raw.get("perf_gate") or {}) if isinstance(raw, dict) else {}
    triggers = perf_cfg.get("triggers") if isinstance(perf_cfg, dict) else None
    if isinstance(triggers, list) and triggers:
        return tuple(str(t) for t in triggers if t)
    return DEFAULT_TRIGGERS


def _override_reminder(config: SuldeConfig) -> tuple[str, str]:
    raw = config.raw.get("enforcement", {}) if isinstance(config.raw, dict) else {}
    perf_cfg = (raw.get("perf_gate") or {}) if isinstance(raw, dict) else {}
    if not isinstance(perf_cfg, dict):
        return DEFAULT_REMINDER_EN, DEFAULT_REMINDER_ZH
    reminder = perf_cfg.get("reminder")
    if isinstance(reminder, str) and reminder.strip():
        return reminder, reminder
    if isinstance(reminder, dict):
        en = str(reminder.get("en") or DEFAULT_REMINDER_EN)
        zh = str(reminder.get("zh") or DEFAULT_REMINDER_ZH)
        return en, zh
    return DEFAULT_REMINDER_EN, DEFAULT_REMINDER_ZH
