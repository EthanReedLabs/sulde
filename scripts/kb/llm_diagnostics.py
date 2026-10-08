"""Allowlisted LLM failure summaries, shared by background callers.

Classification is best-effort diagnostic metadata, never authorization or retry
authority. Raw provider output, command arguments and prompts are never returned.
No files, dependencies, timeout policy or success-output transformations here.
"""
from __future__ import annotations

import errno
import json
import re

MAX_SCAN_CHARS = 8192
MAX_SUMMARY_BYTES = 1024
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")
_ERROR_LINE = re.compile(r"^(?:error|fatal)(?:\s*:\s*|\s+)|^\[(?:error|fatal)\]\s*", re.I)
_CODES = {"insufficient_quota": "quota", "quota_exceeded": "quota",
          "usage_limit_exceeded": "quota", "request_timeout": "timeout",
          "deadline_exceeded": "timeout", "timeout": "timeout"}
_HINTS = {
    "quota": "check provider quota/reset; no automatic retry added",
    "timeout": "check provider availability/deadline; outcome not confirmed",
    "startup_failure": "check executable availability and permissions",
    "invalid_output": "validate the required output schema",
    "unknown": "cause unproven; inspect provider status without exporting raw output",
}


def summary(category: str, *, reason: str = "", facts: str = "") -> str:
    """Only internal, fixed strings may supply reason/facts (not provider text)."""
    value = f"[{category}] LLM command failed; {reason}; {facts}; {_HINTS[category]}"
    # All dynamic fields below are integers/booleans; no redaction by regex needed.
    assert len(value.encode("utf-8")) <= MAX_SUMMARY_BYTES
    return value


def startup_failure(error: OSError | None = None) -> str:
    reason = {errno.ENOENT: "executable_not_found", errno.EACCES: "permission_denied",
              errno.EPERM: "permission_denied", errno.ENOEXEC: "invalid_executable"}.get(
                  getattr(error, "errno", None), "command_setup_failed")
    return summary("startup_failure", reason=reason, facts="command_and_path=omitted")


def timeout_failure() -> str:
    # TimeoutExpired.__str__, cmd, output and stderr can all contain secrets.
    return summary("timeout", reason="process_deadline_expired", facts="raw_output=omitted")


def _window(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_SCAN_CHARS:
        return text, False
    # Inspect complete lines at both ends, not a torn arbitrary substring.
    half = MAX_SCAN_CHARS // 2
    head = text[:half].rsplit("\n", 1)[0] if "\n" in text[:half] else ""
    tail = text[-half:].split("\n", 1)[1] if "\n" in text[-half:] else ""
    # A fence spanning an omitted middle cannot be interpreted safely.
    if head.count("```") % 2 or head.count("~~~") % 2:
        return "", True
    return head + "\n" + tail, True


def _classify(text: str, prompt: str) -> str:
    # Whole known prompt echoes are data, not provider evidence. This comparison
    # also covers a short echo embedded inside a larger diagnostic line.
    if prompt:
        text = text.replace(prompt, "[prompt omitted]")
    text = _ANSI.sub("", text)
    signals: set[str] = set()
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        if {"prompt", "input", "messages"}.intersection(payload):
            return "unknown"
        error = payload["error"]
        # A structured error code is usable; arbitrary message/prompt fields are not.
        for field in ("code", "type"):
            value = error.get(field)
            if isinstance(value, str) and value in _CODES:
                signals.add(_CODES[value])
        return next(iter(signals)) if len(signals) == 1 else "unknown"
    fenced = False
    quoted_block = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            quoted_block = False
        if re.match(r"^(?:(?:quoted|original)\s+)?(?:user\s+)?(?:prompt|request|input)\s*:\s*$", line, re.I):
            quoted_block = True
        if line.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or quoted_block or "[prompt omitted]" in line or not _ERROR_LINE.match(line):
            continue
        if prompt and line in prompt:
            continue
        body = _ERROR_LINE.sub("", line, count=1).lower()
        # Do not search arbitrary quoted explanations for diagnostic vocabulary.
        if body.startswith(("\"", "'", "prompt", "quoted", "example", "user ")):
            continue
        for code, category in _CODES.items():
            if re.match(re.escape(code) + r"(?:\b|:)", body):
                signals.add(category)
        if re.match(r"(?:account )?quota (?:exhausted|exceeded)\b|insufficient quota\b|you(?:'ve| have) hit your usage limit\b|usage limit (?:reached|exceeded)\b", body):
            signals.add("quota")
        if re.match(r"(?:request|operation) timed out\b|deadline exceeded\b", body):
            signals.add("timeout")
    return next(iter(signals)) if len(signals) == 1 else "unknown"


def process_failure(stderr: str, stdout: str, returncode: int, prompt: str) -> str:
    selected = stderr if stderr.strip() else stdout
    window, truncated = _window(selected)
    category = _classify(window, prompt)
    code = str(returncode) if type(returncode) is int and abs(returncode) < 2**32 else "unavailable"
    return summary(category, reason="provider_failure" if category != "unknown" else "no_unique_safe_cause",
                   facts=f"exit={code}; stderr_chars={len(stderr)}; stdout_chars={len(stdout)}; "
                         f"scan={'truncated' if truncated else 'complete'}; raw_output=omitted")
