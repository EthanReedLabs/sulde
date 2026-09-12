"""Noise-gated T1.5 KB recall for the UserPromptSubmit hook."""

from __future__ import annotations

import hashlib
import json
import os
import re
import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any


try:
    kb_cli = SimpleNamespace(
        **runpy.run_path(str(Path(__file__).resolve().with_name("kb_cli.py")))
    )
except (ImportError, OSError) as error:  # pragma: no cover - installation damage
    kb_cli = None  # type: ignore[assignment]
    _KB_CLI_IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    _KB_CLI_IMPORT_ERROR = ""

prompt_noise = SimpleNamespace(
    **runpy.run_path(str(Path(__file__).resolve().with_name("prompt_noise.py")))
)
recall_log = SimpleNamespace(
    **runpy.run_path(str(Path(__file__).resolve().with_name("recall_log.py")))
)


SCORE_MIN = 0.55
MARGIN = 0.10
MAX_INJECTED = 2
SEARCH_TIMEOUT_SECONDS = 5


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _state_dir(_root: Path) -> Path:
    """Mirror the KB index common module without importing its dependency tree."""
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _write_json(path: Path, value: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(path)
    except OSError:
        return


def _detect_platform(root: Path, cwd_value: Any) -> tuple[str, str | None]:
    cwd = str(cwd_value or "")
    if not cwd:
        return cwd, None
    cache_path = _state_dir(root) / "platform-cache.json"
    cache = _read_json(cache_path, {})
    if isinstance(cache, dict) and cache.get(cwd) in {
        "android",
        "ios",
        "flutter",
        "harmonyos",
        None,
    }:
        if cwd in cache:
            return cwd, cache[cwd]

    platform: str | None = None
    project = Path(cwd)
    try:
        if (project / "build.gradle").is_file() or (project / "build.gradle.kts").is_file():
            platform = "android"
        elif (project / "Podfile").is_file() or any(project.glob("*.xcodeproj")):
            platform = "ios"
        elif (project / "pubspec.yaml").is_file():
            platform = "flutter"
        elif (project / "module.json5").is_file():
            platform = "harmonyos"
    except OSError:
        platform = None
    if not isinstance(cache, dict):
        cache = {}
    cache[cwd] = platform
    _write_json(cache_path, cache)
    return cwd, platform


def _session_path(root: Path, session_id: str) -> Path | None:
    if not session_id:
        return None
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id)[:100]
    if not safe or safe in {".", ".."}:
        safe = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return _state_dir(root) / "session-recall" / f"{safe}.json"


def _seen_doc_ids(path: Path | None) -> set[str]:
    if path is None:
        return set()
    value = _read_json(path, {})
    if isinstance(value, dict) and isinstance(value.get("injected"), list):
        return {item for item in value["injected"] if isinstance(item, str)}
    return set()


def _log(
    root: Path,
    cwd: str,
    prompt: str,
    platform: str | None,
    scores: list[float],
    injected: list[str],
    cli_status: str = "ok",
    cli_detail: str = "",
) -> None:
    recall_log.append_kb_recall(
        _state_dir(root),
        cwd=cwd,
        query=prompt,
        platform=platform,
        top_scores=scores,
        injected=injected,
        cli_status=cli_status,
        cli_detail=cli_detail,
    )


def run(payload: dict[str, Any]) -> None:
    root = _plugin_root()
    prompt = str(payload.get("prompt") or "").strip()
    session_id = str(payload.get("session_id") or "")
    cwd, platform = _detect_platform(root, payload.get("cwd"))
    if (
        len(prompt) < 12
        or prompt.startswith("/")
        or prompt_noise.is_recall_noise(prompt)
    ):
        _log(root, cwd, prompt, platform, [], [], "skipped")
        return

    search_query = prompt_noise.bounded_recall_query(prompt)
    arguments = [
        search_query,
        "-k",
        "5",
        "--json",
        "--purpose",
        "route",
    ]
    if platform:
        arguments.extend(["--platform", platform])
    if kb_cli is None:
        _log(
            root,
            cwd,
            prompt,
            platform,
            [],
            [],
            "module_unavailable",
            _KB_CLI_IMPORT_ERROR,
        )
        return
    completed = kb_cli.run_cli(
        root,
        _state_dir(root),
        "search",
        arguments,
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    if not completed.ok:
        detail = completed.detail
        if len(search_query) != len(prompt):
            bounds = (
                f"prompt_chars={len(prompt)} search_chars={len(search_query)}"
            )
            detail = f"{detail}; {bounds}" if detail else bounds
        _log(
            root,
            cwd,
            prompt,
            platform,
            [],
            [],
            completed.status,
            detail,
        )
        return
    try:
        results = json.loads(completed.stdout)
        if not isinstance(results, list):
            raise ValueError("search output is not a list")
    except (ValueError, json.JSONDecodeError) as error:
        _log(
            root,
            cwd,
            prompt,
            platform,
            [],
            [],
            "invalid_output",
            f"{type(error).__name__}: {error}",
        )
        return

    valid = [item for item in results if isinstance(item, dict)]
    valid.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    scores = [round(float(item.get("score", 0.0)), 6) for item in valid[:5]]
    # A route-negative sample is an explicit boundary, not advice.  If it is the
    # strongest match, suppress this turn instead of silently injecting a weaker
    # positive candidate.  Inconclusive knowledge remains searchable but cannot
    # become automatic guidance.
    top_is_boundary = bool(valid) and str(valid[0].get("applicability") or "apply") != "apply"
    eligible = [
        item
        for item in valid
        if str(item.get("applicability") or "apply") == "apply"
        and str(item.get("evidence_status") or "legacy") != "inconclusive"
    ]
    over_threshold = [
        item for item in eligible if float(item.get("score", 0.0)) >= SCORE_MIN
    ]
    selected: list[dict[str, Any]] = []
    top_platform = str(over_threshold[0].get("platform") or "none") if over_threshold else "none"
    if top_platform in {"none", "cross"}:
        competing = over_threshold
    else:
        competing = [
            item
            for item in over_threshold
            if str(item.get("platform") or "none") in {top_platform, "none", "cross"}
        ]
    if top_is_boundary:
        selected = []
    elif len(competing) == 1:
        selected = over_threshold[:1]
    elif len(competing) >= 2:
        gap = float(competing[0]["score"]) - float(competing[1]["score"])
        if gap >= MARGIN:
            selected = competing[:MAX_INJECTED]

    session_path = _session_path(root, session_id)
    seen = _seen_doc_ids(session_path)
    selected = [item for item in selected if str(item.get("doc_id") or "") not in seen]
    selected = selected[:MAX_INJECTED]
    injected = [str(item["doc_id"]) for item in selected if item.get("doc_id")]
    if injected and session_path is not None:
        _write_json(session_path, {"injected": sorted(seen | set(injected))})

    for item in selected:
        print(
            f"[sulde-kb] 可能相关的沉淀(采纳前先读原文): "
            f"{item.get('doc_id', '')} {item.get('title', '')} "
            f"[role={item.get('role', 'general')}] → {item.get('source_path', '')}"
        )
    _log(root, cwd, prompt, platform, scores, injected)
