"""Provider selection and command adapters for Sulde host runtimes.

This module is deliberately independent from Claude/Codex plugin directories.  A
scheduled job selects one provider explicitly; an interactive invocation may infer
its own host only from unambiguous host evidence.  A missing selected provider is
always an error and never triggers a cross-provider fallback.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


PROVIDERS = ("claude", "codex")
PROVIDER_ENV = "SULDE_LLM_PROVIDER"
HOST_PROVIDER_ENV = "SULDE_HOST_PROVIDER"
EXECUTABLE_ENV = {
    "claude": "SULDE_CLAUDE_EXE",
    "codex": "SULDE_CODEX_EXE",
}
CLAUDE_HOST_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_SESSION_ID")
CODEX_HOST_MARKERS = ("CODEX_THREAD_ID", "CODEX_CI")

CAPABILITY_TIERS = ("light", "balanced", "deep")
CAPABILITY_RANK = {name: index for index, name in enumerate(CAPABILITY_TIERS)}
LEGACY_CLAUDE_TIERS = {
    "haiku": "light",
    "sonnet": "balanced",
    "opus": "deep",
}
CLAUDE_MODEL_FOR_TIER = {
    "light": "haiku",
    "balanced": "sonnet",
    "deep": "opus",
}
CLAUDE_THINKING_FOR_TIER = {
    "light": "default",
    "balanced": "think hard",
    "deep": "ultrathink",
}
CODEX_REASONING_LEVELS = ("minimal", "low", "medium", "high", "xhigh", "max")
CODEX_REASONING_RANK = {
    name: index for index, name in enumerate(CODEX_REASONING_LEVELS)
}
CODEX_MIN_REASONING_FOR_TIER = {
    "light": "low",
    "balanced": "medium",
    "deep": "high",
}
CODEX_MODEL_FOR_TIER = {
    "light": "gpt-5.6-luna",
    "balanced": "gpt-5.6-terra",
    "deep": "gpt-5.6-sol",
}
CODEX_TIER_FOR_MODEL = {
    model: tier for tier, model in CODEX_MODEL_FOR_TIER.items()
}
CODEX_TIER_FOR_MODEL["gpt-5.6"] = "deep"


class ProviderError(RuntimeError):
    """The configured host provider cannot be selected safely."""


def normalize_capability_tier(value: str) -> str:
    """Normalize the provider-neutral task tier, accepting legacy Claude labels."""
    normalized = value.strip().lower().replace("_", "-")
    normalized = LEGACY_CLAUDE_TIERS.get(normalized, normalized)
    if normalized not in CAPABILITY_RANK:
        expected = ", ".join(CAPABILITY_TIERS)
        raise ProviderError(
            f"unsupported capability tier: {value!r}; expected {expected}"
        )
    return normalized


def legacy_task_profile(
    *,
    model: str | None = None,
    thinking_mode: str | None = None,
) -> tuple[str | None, list[str]]:
    """Translate archived Claude task metadata without making it new truth.

    New task files must use ``capability_tier``. This adapter exists only so an
    archived task can still be executed during the migration window.
    """
    warnings: list[str] = []
    normalized_model = _normalized_optional(model)
    raw_thinking = _normalized_optional(thinking_mode)
    normalized_thinking = raw_thinking.replace("-", " ") if raw_thinking else None
    tier = LEGACY_CLAUDE_TIERS.get(normalized_model or "")
    thinking_tiers = {
        "default": "light",
        "think": "light",
        "think hard": "balanced",
        "ultrathink": "deep",
    }
    thinking_tier = thinking_tiers.get(normalized_thinking or "")
    if normalized_model:
        if tier is None:
            warnings.append(f"unrecognized legacy model metadata: {model}")
        else:
            warnings.append(
                f"legacy model:{normalized_model} migrated in memory to capability_tier:{tier}"
            )
    if normalized_thinking:
        if thinking_tier is None:
            warnings.append(
                f"unrecognized legacy thinking metadata: {thinking_mode}"
            )
        else:
            warnings.append(
                "legacy thinking metadata migrated in memory to "
                f"capability_tier:{thinking_tier}"
            )
            if tier is None or CAPABILITY_RANK[thinking_tier] > CAPABILITY_RANK[tier]:
                tier = thinking_tier
    return tier, warnings


def _normalized_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _claude_model_matches(current_model: str | None, target_model: str) -> bool:
    normalized = _normalized_optional(current_model)
    if normalized is None:
        return False
    return normalized == target_model or target_model in normalized.split("-")


def _codex_model_tier(current_model: str | None) -> str | None:
    normalized = _normalized_optional(current_model)
    if normalized is None:
        return None
    return CODEX_TIER_FOR_MODEL.get(normalized)


def validate_dispatch_instructions(
    provider: str,
    instructions: list[str],
) -> None:
    """Reject provider-specific control leakage in a rendered short dispatch."""
    normalized_provider = provider.strip().lower()
    if normalized_provider not in PROVIDERS:
        raise ProviderError(f"unsupported Sulde provider: {provider}")
    rendered = "\n".join(instructions)
    if normalized_provider == "codex":
        forbidden = (
            (r"(?im)^\s*/model\s+(?:claude(?:-[\w.]+)*|opus|sonnet|haiku)\b", "Claude model command"),
            (r"(?im)^\s*/mode(?:\s|$)", "Claude mode command"),
            (r"(?im)^\s*/assign(?:\s|$)", "Claude assign command"),
            (r"(?im)^\s*/clear(?:\s|$)", "Claude clear command"),
            (r"(?im)^\s*/ralph-loop(?:\s|$)", "Claude ralph-loop command"),
            (r"(?i)\b(?:ultrathink|think hard)\b", "Claude thinking hint"),
        )
    else:
        forbidden = (
            (r"(?im)^\s*/reasoning(?:\s|$)", "Codex reasoning command"),
            (r"(?im)^\s*/new(?:\s|$)", "Codex new-session command"),
            (r"(?i)\bgpt-5\.[\w.-]+\b", "Codex model identifier"),
        )
    violations = [label for pattern, label in forbidden if re.search(pattern, rendered)]
    if violations:
        raise ProviderError(
            f"{normalized_provider} dispatch contains foreign-provider controls: "
            + ", ".join(violations)
        )


def model_dispatch_plan(
    provider: str,
    capability_tier: str,
    *,
    current_model: str | None = None,
    current_capability_tier: str | None = None,
    current_effort: str | None = None,
    required_effort: str | None = None,
    model_advice: bool = False,
) -> dict[str, Any]:
    """Return provider-native model/reasoning actions for one interactive task.

    Task files carry only a provider-neutral capability floor. Claude translates
    that floor to its native model family. Codex preserves a capable current
    model without inspecting capability by default. Model/reasoning suggestions
    are opt-in for interactive Codex dispatch; this does not change the separate
    managed-runtime model selection policy.
    """
    normalized_provider = provider.strip().lower()
    if normalized_provider not in PROVIDERS:
        raise ProviderError(f"unsupported Sulde provider: {provider}")
    tier = normalize_capability_tier(capability_tier)
    model = _normalized_optional(current_model)
    effort = _normalized_optional(current_effort)
    requested_effort = _normalized_optional(required_effort)
    actions: list[dict[str, str]] = []
    notices: list[str] = []

    if normalized_provider == "claude":
        if requested_effort is not None:
            raise ProviderError("required_effort is only valid for a Codex dispatch")
        target_model = CLAUDE_MODEL_FOR_TIER[tier]
        if not _claude_model_matches(model, target_model):
            actions.append(
                {
                    "kind": "model",
                    "command": f"/model {target_model}",
                    "selection": target_model,
                }
            )
        target: dict[str, str | None] = {
            "model": target_model,
            "model_policy": "provider-native-tier",
            "thinking_hint": CLAUDE_THINKING_FOR_TIER[tier],
            "minimum_reasoning_effort": None,
        }
    else:
        if model in LEGACY_CLAUDE_TIERS:
            raise ProviderError(
                "Codex current_model cannot be a Claude model label; read the "
                "current Codex session model before rendering the dispatch"
            )
        current_tier = (
            normalize_capability_tier(current_capability_tier)
            if current_capability_tier
            else _codex_model_tier(model)
        )
        if not model_advice:
            if requested_effort is not None:
                raise ProviderError("required_effort requires explicit --model-advice")
            if effort is not None and effort not in CODEX_REASONING_RANK:
                raise ProviderError(f"unsupported Codex reasoning effort: {current_effort!r}")
            return {
                "provider": normalized_provider,
                "capability_tier": tier,
                "model_advice": False,
                "current": {"model": model, "capability_tier": current_tier,
                            "reasoning_effort": effort},
                "target": {"model": model, "model_policy": "preserve-current-dispatch-only",
                           "thinking_hint": None, "minimum_reasoning_effort": None},
                "actions": [],
                "notices": [],
                # Ready to dispatch, not a claim that model capability was verified.
                "ready": True,
            }
        target_model = CODEX_MODEL_FOR_TIER[tier]
        if current_tier is None or CAPABILITY_RANK[current_tier] < CAPABILITY_RANK[tier]:
            actions.append(
                {
                    "kind": "model",
                    "command": "/model",
                    "selection": (
                        f"{target_model}（若当前可用列表无此型号，选择 {tier} 档"
                        "或更高的 Codex 模型）"
                    ),
                }
            )
        elif CAPABILITY_RANK[current_tier] > CAPABILITY_RANK[tier]:
            notices.append(
                "当前模型高于任务最低能力档；可直接保留，若需要降本再用 /model 下调。"
            )

        minimum_effort = requested_effort or CODEX_MIN_REASONING_FOR_TIER[tier]
        if minimum_effort not in CODEX_REASONING_RANK:
            expected = ", ".join(CODEX_REASONING_LEVELS)
            raise ProviderError(
                f"unsupported required Codex reasoning effort: {required_effort!r}; "
                f"expected {expected}"
            )
        if effort is not None and effort not in CODEX_REASONING_RANK:
            expected = ", ".join(CODEX_REASONING_LEVELS)
            raise ProviderError(
                f"unsupported Codex reasoning effort: {current_effort!r}; "
                f"expected {expected}"
            )
        if (
            effort is None
            or CODEX_REASONING_RANK[effort]
            < CODEX_REASONING_RANK[minimum_effort]
        ):
            actions.append(
                {
                    "kind": "reasoning",
                    "command": "/reasoning",
                    "selection": f"{minimum_effort} 或更高",
                }
            )
        target = {
            "model": (
                target_model
                if any(action["kind"] == "model" for action in actions)
                else model
            ),
            "model_policy": "preserve-current-if-capable",
            "thinking_hint": None,
            "minimum_reasoning_effort": minimum_effort,
        }

    return {
        "provider": normalized_provider,
        "capability_tier": tier,
        "model_advice": True,
        "current": {
            "model": model,
            "capability_tier": (
                normalize_capability_tier(current_capability_tier)
                if current_capability_tier
                else (_codex_model_tier(model) if normalized_provider == "codex" else None)
            ),
            "reasoning_effort": effort,
        },
        "target": target,
        "actions": actions,
        "notices": notices,
        "ready": not actions,
    }


def render_dispatch_instructions(
    plan: Mapping[str, Any],
    *,
    task_path: str,
    fresh_session: bool = False,
) -> list[str]:
    """Render copyable, provider-native interactive dispatch instructions."""
    provider = str(plan.get("provider") or "")
    if provider not in PROVIDERS:
        raise ProviderError(f"unsupported Sulde provider: {provider}")
    lines: list[str] = []
    if fresh_session:
        lines.append("/clear" if provider == "claude" else "/new")
    actions = plan.get("actions") or []
    for action in actions:
        if not isinstance(action, Mapping):
            raise ProviderError("invalid dispatch action")
        command = str(action.get("command") or "")
        selection = str(action.get("selection") or "")
        if not command:
            raise ProviderError("dispatch action is missing command")
        lines.append(command)
        if selection and command in {"/model", "/reasoning"}:
            lines.append(f"选择:{selection}")
    if not actions and plan.get("model_advice") is True:
        lines.append("当前模型与推理档位已满足任务要求，无需切换。")
    if provider == "claude":
        lines.append(f"/assign 任务文件:{task_path}")
    else:
        lines.append(f"执行任务文件:{task_path}")
    validate_dispatch_instructions(provider, lines)
    return lines


def _is_truthy(value: str | None) -> bool:
    return bool(value and value.strip() and value.strip().lower() not in {"0", "false", "no"})


def _host_evidence(environment: Mapping[str, str]) -> set[str]:
    evidence: set[str] = set()
    if any(_is_truthy(environment.get(name)) for name in CLAUDE_HOST_MARKERS):
        evidence.add("claude")
    if any(_is_truthy(environment.get(name)) for name in CODEX_HOST_MARKERS):
        evidence.add("codex")
    return evidence


def resolve_executable(
    provider: str,
    *,
    environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> str | None:
    """Resolve one provider executable without looking at the other provider."""
    if provider not in PROVIDERS:
        raise ProviderError(f"unsupported Sulde provider: {provider}")
    current = os.environ if environment is None else environment
    override = current.get(EXECUTABLE_ENV[provider], "").strip()
    if override:
        expanded = Path(override).expanduser()
        if expanded.is_file():
            return str(expanded)
        discovered = which(override)
        return discovered
    return which(provider)


def select_provider(
    requested: str | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[str, str]:
    """Return ``(provider, executable)`` under the no-silent-fallback contract."""
    current = os.environ if environment is None else environment
    configured = (
        requested
        or current.get(PROVIDER_ENV)
        or current.get(HOST_PROVIDER_ENV)
        or "auto"
    ).strip().lower()
    if configured not in (*PROVIDERS, "auto"):
        raise ProviderError(
            f"invalid provider {configured!r}; expected claude, codex, or auto"
        )

    if configured in PROVIDERS:
        executable = resolve_executable(
            configured, environment=current, which=which
        )
        if executable is None:
            variable = EXECUTABLE_ENV[configured]
            raise ProviderError(
                f"selected provider {configured} is unavailable; install/authenticate it "
                f"or set {variable}. Sulde will not fall back to another provider"
            )
        return configured, executable

    evidence = _host_evidence(current)
    if len(evidence) == 1:
        provider = next(iter(evidence))
        executable = resolve_executable(provider, environment=current, which=which)
        if executable is None:
            raise ProviderError(
                f"detected {provider} host but its executable is unavailable; "
                "cross-provider fallback is disabled"
            )
        return provider, executable
    if len(evidence) > 1:
        raise ProviderError(
            f"conflicting host evidence: {', '.join(sorted(evidence))}; "
            f"set {PROVIDER_ENV}=claude or codex"
        )

    installed = {
        provider: executable
        for provider in PROVIDERS
        if (executable := resolve_executable(provider, environment=current, which=which))
        is not None
    }
    if len(installed) == 1:
        return next(iter(installed.items()))
    if not installed:
        raise ProviderError(
            "neither Claude Code nor Codex CLI is available; install one runtime first"
        )
    raise ProviderError(
        "both Claude Code and Codex CLI are available but no host owns this invocation; "
        f"set {PROVIDER_ENV}=claude or codex"
    )


def cognitive_command(provider: str, executable: str) -> list[str]:
    """Build the read-only/headless command used by Sulde cognitive organs."""
    if provider == "claude":
        return [
            executable,
            "-p",
            "--output-format",
            "text",
            "--no-session-persistence",
            "--safe-mode",
            "--permission-mode",
            "plan",
            "--tools",
            "",
        ]
    if provider == "codex":
        return [
            executable,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "-",
        ]
    raise ProviderError(f"unsupported Sulde provider: {provider}")


def task_command(
    provider: str,
    executable: str,
    *,
    worktree: Path,
    report: Path,
    effort: str,
) -> list[str]:
    """Build one isolated, workspace-writing task command for L3 execution."""
    if effort not in {"low", "medium", "high"}:
        raise ProviderError(f"unsupported effort: {effort}")
    if provider == "codex":
        return [
            executable,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "-C",
            str(worktree),
            "--sandbox",
            "workspace-write",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
            "--output-last-message",
            str(report),
            "-c",
            'approval_policy="never"',
            "-c",
            f'model_reasoning_effort="{effort}"',
            "-",
        ]
    if provider == "claude":
        native_sandbox = os.name != "nt"
        settings = {
            "permissions": {
                "deny": [
                    "Bash(git commit *)",
                    "Bash(git push *)",
                    "Bash(git reset --hard *)",
                    "Bash(git clean *)",
                ]
            },
            "sandbox": {
                "enabled": native_sandbox,
                "failIfUnavailable": native_sandbox,
                "autoAllowBashIfSandboxed": True,
                "allowUnsandboxedCommands": False,
            },
        }
        return [
            executable,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-hook-events",
            "--no-session-persistence",
            "--safe-mode",
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--permission-mode",
            "acceptEdits" if native_sandbox else "auto",
            "--settings",
            json.dumps(settings, ensure_ascii=True, separators=(",", ":")),
            "--effort",
            effort,
        ]
    raise ProviderError(f"unsupported Sulde provider: {provider}")
