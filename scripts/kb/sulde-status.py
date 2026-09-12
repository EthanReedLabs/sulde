#!/usr/bin/env python3
"""Fast, dependency-free health status for the local Sulde knowledge base."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from corpus_manifest import ManifestError, load_manifest  # noqa: E402
from event_observer import status_projection as event_status_projection  # noqa: E402
from host_capabilities import readiness_projection as host_readiness_projection  # noqa: E402
from intervention import inventory as intervention_inventory  # noqa: E402
from recall_log import LOG_FILENAME, classify_recall_source  # noqa: E402
from launcher_contract import verify_installation as verify_launcher_installation  # noqa: E402
from operational_readiness import (  # noqa: E402
    project as operational_readiness_projection,
    scheduler_process_projection as scheduler_health_projection,
)
from production_recovery_readiness import observe_recovery_truth  # noqa: E402
from life_health import domains as health_domains
from sulde_status_snapshot import (  # noqa: E402
    read_snapshot as read_statusline_snapshot,
    write_snapshot as write_statusline_snapshot,
)


DAY_SECONDS = 24 * 60 * 60
DISTILL_STALE_SECONDS = 2 * DAY_SECONDS
LIFE_STALE_SECONDS = 12 * 60 * 60


def configure_utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="strict")
            except (LookupError, OSError):
                pass


configure_utf8_stdio()


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def age_seconds(timestamp: datetime | None, now: datetime) -> int | None:
    if timestamp is None:
        return None
    return max(0, int((now - timestamp).total_seconds()))


def read_kb(database: Path) -> dict[str, Any] | None:
    try:
        if not database.is_file():
            return None
        with sqlite3.connect(str(database), timeout=0.05) as connection:
            docs, chunks = connection.execute(
                "SELECT COUNT(DISTINCT doc_id), COUNT(*) FROM chunks"
            ).fetchone()
            edges = connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            row = connection.execute(
                "SELECT value FROM meta WHERE key = 'corpus_fingerprint'"
            ).fetchone()
        return {
            "kb_docs": int(docs),
            "kb_chunks": int(chunks),
            "kb_edges": int(edges),
            "kb_index_fingerprint": str(row[0]) if row else None,
        }
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None


def read_memory(database: Path, now: datetime) -> dict[str, Any] | None:
    try:
        if not database.is_file():
            return None
        local_today = now.astimezone().date()
        with sqlite3.connect(str(database), timeout=0.05) as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM mem_entries INDEXED BY mem_entries_pending"
            ).fetchone()[0]
            pending = connection.execute(
                "SELECT COUNT(*) FROM mem_entries WHERE embedded = 0"
            ).fetchone()[0]
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(mem_entries)")
            }
            if "source_host" in columns:
                claude = connection.execute(
                    """SELECT COUNT(*) FROM mem_entries
                       WHERE source_host='claude'
                          OR session_id LIKE 'claude:%'
                          OR substr(session_id,1,7)='claude_'"""
                ).fetchone()[0]
                codex = connection.execute(
                    """SELECT COUNT(*) FROM mem_entries
                       WHERE source_host='codex'
                          OR session_id LIKE 'codex:%'
                          OR substr(session_id,1,6)='codex_'"""
                ).fetchone()[0]
                imported = connection.execute(
                    "SELECT COUNT(*) FROM mem_entries WHERE source_host='import'"
                ).fetchone()[0]
                unknown = connection.execute(
                    """SELECT COUNT(*) FROM mem_entries
                       WHERE source_host='unknown'
                         AND session_id NOT LIKE 'claude:%'
                         AND substr(session_id,1,7)<>'claude_'
                         AND session_id NOT LIKE 'codex:%'
                         AND substr(session_id,1,6)<>'codex_'"""
                ).fetchone()[0]
            else:
                claude = connection.execute(
                    """SELECT COUNT(*) FROM mem_entries
                       WHERE session_id LIKE 'claude:%'
                          OR substr(session_id,1,7)='claude_'"""
                ).fetchone()[0]
                codex = connection.execute(
                    """SELECT COUNT(*) FROM mem_entries
                       WHERE session_id LIKE 'codex:%'
                          OR substr(session_id,1,6)='codex_'"""
                ).fetchone()[0]
                imported = 0
                unknown = max(int(total) - int(claude) - int(codex), 0)
            recent = connection.execute(
                "SELECT ts FROM mem_entries ORDER BY id DESC"
            )
            today_count = 0
            latest: datetime | None = None
            for row in recent:
                timestamp = parse_timestamp(row[0])
                if latest is None and timestamp is not None:
                    latest = timestamp
                if timestamp is None:
                    continue
                local_date = timestamp.astimezone().date()
                if local_date == local_today:
                    today_count += 1
                elif local_date < local_today:
                    break
        return {
            "mem_total": int(total),
            "mem_today": today_count,
            "mem_pending_embedding": int(pending),
            "mem_claude": int(claude),
            "mem_codex": int(codex),
            "mem_import": int(imported),
            "mem_unknown_source": int(unknown),
            "mem_last_capture_ts": latest.isoformat() if latest else None,
            "mem_last_capture_age_seconds": age_seconds(latest, now),
        }
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None


def read_file_time(path: Path, now: datetime) -> dict[str, Any] | None:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        return {
            "harvest_last_ts": modified.isoformat(),
            "harvest_age_seconds": age_seconds(modified, now),
        }
    except (OSError, ValueError, OverflowError):
        return None


def read_distill(path: Path, now: datetime) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        timestamp = parse_timestamp(payload.get("ts"))
        last_id = payload.get("last_id")
        return {
            "distill_last_id": last_id if isinstance(last_id, int) else None,
            "distill_last_ts": timestamp.isoformat() if timestamp else None,
            "distill_age_seconds": age_seconds(timestamp, now),
        }
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None


def read_life(path: Path, now: datetime) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        generated = parse_timestamp(payload.get("generated_at"))
        levels = payload.get("levels", {})
        evolution = payload.get("evolution", {})
        return {
            "life_status": str(payload.get("status", "unknown")),
            "life_age_seconds": age_seconds(generated, now),
            "life_levels": {
                name: str(value.get("status", "unknown"))
                for name, value in levels.items()
                if isinstance(value, dict)
            },
            "life_evolution_status": str(evolution.get("status", "unknown")) if isinstance(evolution, dict) else "unknown",
            "life_evolution_active": int(evolution.get("active", 0)) if isinstance(evolution, dict) else 0,
            "life_evolution_recommendations": int(evolution.get("recommendations", 0)) if isinstance(evolution, dict) else 0,
        }
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None


def read_runtime_owner(path: Path) -> dict[str, Any]:
    """Read the persisted single-scheduler owner without invoking either LLM."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        provider = str(payload.get("provider", "")).lower()
        executable = str(payload.get("executable", ""))
        if provider not in {"claude", "codex"} or not executable:
            raise ValueError("invalid runtime owner")
        expanded = Path(executable).expanduser()
        available = expanded.is_file() or shutil.which(executable) is not None
        owner_status = str(payload.get("status") or "legacy_unverified")
        managed_labels = payload.get("managed_labels")
        retired_labels = payload.get("retired_labels")
        return {
            "runtime_provider": provider,
            "runtime_executable": executable,
            "runtime_available": available,
            "runtime_scheduler": str(payload.get("scheduler", "unknown")),
            "runtime_owner_status": owner_status,
            "runtime_generation": str(payload.get("generation") or ""),
            "runtime_root": str(payload.get("runtime_root") or payload.get("source_root") or ""),
            "runtime_tree_sha256": str(payload.get("runtime_tree_sha256") or ""),
            "runtime_managed_labels": [
                str(label)
                for label in (managed_labels if isinstance(managed_labels, list) else [])
                if str(label).startswith("com.sulde.")
            ],
            "runtime_retired_labels": [
                str(label)
                for label in (retired_labels if isinstance(retired_labels, list) else [])
                if str(label).startswith("com.sulde.")
            ],
            "runtime_owner_installed_at": payload.get("installed_at"),
        }
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        configured = os.environ.get("SULDE_LLM_PROVIDER") or os.environ.get(
            "SULDE_HOST_PROVIDER"
        )
        return {
            "runtime_provider": configured if configured in {"claude", "codex"} else None,
            "runtime_executable": None,
            "runtime_available": None,
            "runtime_scheduler": None,
            "runtime_owner_status": "missing_or_invalid",
            "runtime_generation": "",
            "runtime_root": "",
            "runtime_tree_sha256": "",
            "runtime_managed_labels": [],
            "runtime_retired_labels": [],
            "runtime_owner_installed_at": None,
        }


def read_recall(path: Path, now: datetime) -> dict[str, Any] | None:
    try:
        today = now.astimezone().date()
        counts = {"mem": 0, "kb": 0}
        unclassified = 0
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                    timestamp = parse_timestamp(payload.get("ts"))
                    if timestamp is None or timestamp.astimezone().date() != today:
                        continue
                    source = classify_recall_source(payload)
                    if source is None:
                        unclassified += 1
                    else:
                        counts[source] += len(payload["injected"])
                except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                    continue
        return {
            "recall_today_mem": counts["mem"],
            "recall_today_kb": counts["kb"],
            "recall_today_unclassified_rows": unclassified,
        }
    except (OSError, UnicodeError):
        return None


def read_event_observation(home: Path) -> dict[str, Any]:
    """Keep contract drift visible without exposing source rows or paths."""
    try:
        return event_status_projection(home)
    except Exception as error:
        return {
            "event_observation_privacy_mode": "unknown",
            "event_observation_privacy_healthy": False,
            "event_observation_enabled": False,
            "event_observation_export_enabled": False,
            "event_contract_schema": "sulde-observation-event-v1",
            "event_contract_healthy": False,
            "event_contract_violations": 1,
            "event_sources_discovered": 0,
            "event_sources_healthy": 0,
            "event_sources_unreadable": 1,
            "event_rows_total": 0,
            "event_observations_total": 0,
            "event_correlated_total": 0,
            "event_observation_latest_at": None,
            "event_observations_by_domain": {},
            "event_observation_error": type(error).__name__,
        }


def read_intervention_status(home: Path) -> dict[str, Any]:
    """Expose durable unknown-effect truth even when the OS alert was missed."""
    try:
        return intervention_inventory(home)
    except Exception as error:
        return {
            "intervention_stores": 0,
            "effect_attempts": 0,
            "effect_unknown": 0,
            "effect_verifying": 0,
            "effect_blocking": 0,
            "interventions_open": 0,
            "interventions_resolved": 0,
            "intervention_invalid_stores": 1,
            "intervention_oldest_open_at": None,
            "intervention_error": type(error).__name__,
        }


def read_host_readiness(
    home: Path,
    provider: str | None,
    *,
    session_id: str | None = None,
    workspace: Path | str | None = None,
    approval_required: bool = False,
) -> dict[str, Any]:
    """Expose current-generation, session-bound hook evidence."""
    try:
        return host_readiness_projection(
            home,
            provider=provider,
            session_id=session_id,
            workspace=workspace,
            approval_required=approval_required,
        )
    except Exception as error:
        return {
            "schema": "sulde-host-capability-contract-v1",
            "provider": provider or "any",
            "status": "unavailable",
            "error": type(error).__name__,
        }


def current_fingerprint(root: Path = ROOT) -> str | None:
    try:
        return load_manifest(root, verify_files=True).corpus_sha256
    except (OSError, UnicodeError, ManifestError):
        return None


def collect(*, scheduler_probe: dict[str, Any] | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    home = kb_home()
    sources: dict[str, dict[str, Any] | None] = {
        "kb": read_kb(home / "kb.db"),
        "memory": read_memory(home / "memory.db", now),
        "harvest": read_file_time(home / "codex-harvest-state.json", now),
        "distill": read_distill(home / "distill-state.json", now),
        "recall": read_recall(home / LOG_FILENAME, now),
        "life": read_life(home / "life/state.json", now),
    }
    missing = [name for name, value in sources.items() if value is None]
    status: dict[str, Any] = {
        "ok": not missing,
        "warn": bool(missing),
        "kb_home": str(home),
        "checked_at": now.isoformat(),
        "missing_sources": missing,
    }
    for value in sources.values():
        if value:
            status.update(value)
    status.update(read_event_observation(home))
    status.update(read_intervention_status(home))
    fingerprint = current_fingerprint()
    status["kb_current_fingerprint"] = fingerprint
    indexed = status.get("kb_index_fingerprint")
    status["kb_index_stale"] = (
        indexed != fingerprint if indexed is not None and fingerprint is not None else None
    )
    launcher_health = verify_launcher_installation(home, expected_source_root=ROOT)
    status["launcher_contract_healthy"] = bool(launcher_health["healthy"])
    status["launcher_contract_spec_version"] = launcher_health["spec_version"]
    status["launcher_contract_issues"] = launcher_health["issues"]
    status.update(read_fleet_summary())
    status.update(read_runtime_owner(home / "runtime-owner.json"))
    runtime_provider = status.get("runtime_provider")
    try:
        operational = operational_readiness_projection(
            home,
            # Interactive provider comes from the current host environment;
            # a background process falls back to runtime-owner.json. Scheduler
            # ownership must not overwrite an unrelated interactive identity.
            provider=None,
            scheduler_probe=scheduler_probe,
            recovery_truth=observe_recovery_truth(home),
        )
    except Exception as error:
        operational = {
            "schema": "sulde-operational-readiness-v1",
            "status": "unavailable",
            "provider": runtime_provider,
            "reasons": [type(error).__name__],
            "gates": {},
            "host_readiness": {
                "schema": "sulde-host-capability-contract-v1",
                "provider": runtime_provider or "any",
                "status": "unavailable",
            },
        }
    status["operational_readiness"] = operational
    status["health_domains"] = health_domains(home, operational)
    status["host_readiness"] = operational.get("host_readiness", {})
    status["recovery_readiness"] = operational.get(
        "recovery_readiness",
        {
            "schema": "sulde-recovery-readiness-v1",
            "status": "unavailable",
            "reasons": ["recovery_projection_unavailable"],
        },
    )
    # JSON, statusline, exit code, and notification all consume this one
    # operational projection. The raw OS probe is retained only inside the
    # scheduler domain as diagnostic input, never as a competing readiness.
    status["scheduler_health"] = operational.get(
        "scheduler_readiness",
        {
            "status": "unavailable",
            "reasons": ["scheduler_projection_unavailable"],
            "process_probe": scheduler_probe,
        },
    )
    pending_embedding = status.get("mem_pending_embedding")
    status["memory_embedding_health"] = {
        "status": (
            "unavailable"
            if not isinstance(pending_embedding, int)
            else "backlogged"
            if pending_embedding > 500
            else "ready"
        ),
        "pending": pending_embedding,
        "blocks_interactive": False,
        "blocks_scheduler": False,
    }
    # 各时龄字段可能为 None(库为空/ts 不可解析),.get 默认值挡不住"键在值 None"
    abnormal = (
        status["kb_index_stale"] is True
        or (status.get("harvest_age_seconds") or 0) > DAY_SECONDS
        or (status.get("mem_last_capture_age_seconds") or 0) > DAY_SECONDS
        or status.get("life_status") not in {"ready"}
        or (status.get("life_age_seconds") or 0) > LIFE_STALE_SECONDS
        or status["launcher_contract_healthy"] is False
        or status.get("event_observation_privacy_healthy") is False
        or (status.get("event_contract_violations") or 0) > 0
        or (status.get("interventions_open") or 0) > 0
        or (status.get("effect_blocking") or 0) > 0
        or (status.get("intervention_invalid_stores") or 0) > 0
        or status.get("runtime_available") is False
        or status["scheduler_health"].get("status") != "ready"
        or operational.get("status") != "ready"
    )
    status["warn"] = bool(missing or abnormal)
    status["ok"] = not status["warn"]
    return status


def read_fleet_summary() -> dict[str, int]:
    """Fleet failures must never slow or break the health light."""
    try:
        from fleet import collect_task_summary

        value = collect_task_summary()
        return {
            "fleet_running": int(value.get("fleet_running", 0)),
            "fleet_stalled": int(value.get("fleet_stalled", 0)),
        }
    except Exception:
        return {"fleet_running": 0, "fleet_stalled": 0}


def compact_number(value: int) -> str:
    if value < 1000:
        return str(value)
    rendered = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
    return f"{rendered}k"


def relative_age(seconds: int | None) -> str:
    if seconds is None:
        return "未知"
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60}m前"
    if seconds < DAY_SECONDS:
        return f"{seconds // 3600}h前"
    return f"{seconds // DAY_SECONDS}d前"


STATUSLINE_OBSERVER_LABELS = {"com.sulde.status-notify"}


def statusline_scheduler_issues(status: dict[str, Any]) -> list[str]:
    """Return scheduler failures that are independent of the status observer."""
    scheduler = status.get("scheduler_health")
    if not isinstance(scheduler, dict) or scheduler.get("status") == "ready":
        return []
    missing = [str(label) for label in scheduler.get("missing_labels", [])]
    failed_labels = (
        scheduler.get("failed_labels", {})
        if isinstance(scheduler.get("failed_labels"), dict)
        else {}
    )
    failed = [
        str(label)
        for label in failed_labels
        if str(label) not in STATUSLINE_OBSERVER_LABELS
    ]
    retired = [str(label) for label in scheduler.get("retired_loaded_labels", [])]
    specific = [
        *(f"missing:{label}" for label in missing),
        *(f"failed:{label}" for label in failed),
        *(f"retired:{label}" for label in retired),
    ]
    if specific:
        return specific
    reasons = scheduler.get("reasons")
    rendered_reasons = (
        [str(reason) for reason in reasons] if isinstance(reasons, list) else ["unknown"]
    )
    # A previous warning exit from the observer is the one label-level failure
    # that cannot independently make the observed scheduler unhealthy.
    if (
        failed_labels
        and all(str(label) in STATUSLINE_OBSERVER_LABELS for label in failed_labels)
        and not missing
        and not retired
        and set(rendered_reasons) <= {"managed_actor_last_exit_nonzero"}
    ):
        return []
    return rendered_reasons


def interactive_waiting_label(status: dict[str, Any]) -> str | None:
    """Classify the two non-fault interactive prompt waiting states."""
    operational = status.get("operational_readiness")
    if (
        not isinstance(operational, dict)
        or operational.get("readiness_scope") != "interactive"
        or operational.get("status") == "ready"
    ):
        return None
    reasons = operational.get("reasons")
    reason_set = (
        {str(reason) for reason in reasons}
        if isinstance(reasons, list)
        else set()
    )
    if not reason_set or not reason_set <= {
        "host_interactive_fresh",
        "host_supervision_fresh",
    }:
        return None
    host = operational.get("host_readiness")
    capabilities = host.get("capabilities") if isinstance(host, dict) else None
    if not isinstance(capabilities, dict):
        return None
    session_context = capabilities.get("session_context")
    prompt_control = capabilities.get("prompt_control")
    if (
        not isinstance(session_context, dict)
        or session_context.get("status") != "live_verified"
        or not isinstance(prompt_control, dict)
        or prompt_control.get("status") != "unobserved"
    ):
        return None
    for capability_id, capability in capabilities.items():
        if (
            capability_id != "prompt_control"
            and isinstance(capability, dict)
            and capability.get("required_for_interactive") is True
            and capability.get("status") != "live_verified"
        ):
            return None
    stale_prompts = prompt_control.get("stale_observations")
    if isinstance(stale_prompts, int) and stale_prompts > 0:
        return "空闲，等待下一条提示"
    return "等待首个提示"


def statusline_healthy(status: dict[str, Any]) -> bool:
    """Project local runtime health without inheriting historical audit debt."""
    operational = status.get("operational_readiness")
    interactive_operational_ready = not (
        isinstance(operational, dict)
        and operational.get("readiness_scope") == "interactive"
        and operational.get("status") != "ready"
    )
    return not (
        bool(status.get("missing_sources"))
        or status.get("kb_index_stale") is True
        or (status.get("harvest_age_seconds") or 0) > DAY_SECONDS
        or (status.get("distill_age_seconds") or 0) > DISTILL_STALE_SECONDS
        or status.get("life_status") not in {None, "ready"}
        or (status.get("life_age_seconds") or 0) > LIFE_STALE_SECONDS
        or status.get("runtime_available") is False
        or status.get("launcher_contract_healthy") is False
        or bool(statusline_scheduler_issues(status))
        or not interactive_operational_ready
        or (status.get("fleet_stalled") or 0) > 0
    )


def statusline(status: dict[str, Any]) -> str:
    missing = status["missing_sources"]
    if len(missing) == 6:
        line = "sulde \033[31m●\033[0m"
    elif missing:
        line = f"sulde \033[33m●\033[0m 缺:{','.join(missing)}"
    else:
        distill_age = status.get("distill_age_seconds")
        distill = (
            "今天"
            if isinstance(distill_age, int) and distill_age < DAY_SECONDS
            else relative_age(distill_age)
        )
        mark = "\033[32m●\033[0m" if statusline_healthy(status) else "\033[33m●\033[0m"
        line = (
            f"sulde {mark} kb:{status['kb_docs']}·边{status['kb_edges']} "
            f"mem:{compact_number(status['mem_total'])}(+{status['mem_today']}) "
            f"待嵌:{status['mem_pending_embedding']} "
            f"收割:{relative_age(status['harvest_age_seconds'])} 蒸馏:{distill}"
        )
        levels = status.get("life_levels", {})
        if levels:
            line += " " + "/".join(f"{name}:{str(levels.get(name, '?'))[:1]}" for name in ("L2", "L3", "L4"))
        if status.get("life_evolution_status"):
            line += f"/E:{str(status['life_evolution_status'])[:1]}"
        if status.get("runtime_provider"):
            line += f" H:{str(status['runtime_provider'])[:1]}"
    stalled = status.get("fleet_stalled", 0)
    operational = status.get("operational_readiness")
    interactive_unready = (
        isinstance(operational, dict)
        and operational.get("readiness_scope") == "interactive"
        and operational.get("status") != "ready"
    )
    waiting = None
    if interactive_unready:
        waiting = interactive_waiting_label(status)
        if waiting:
            line = f"sulde \033[33m●\033[0m {waiting}"
        else:
            reasons = operational.get("reasons")
            first = str(reasons[0]) if isinstance(reasons, list) and reasons else "unknown"
            recovery = status.get("recovery_readiness")
            if not isinstance(recovery, dict) and isinstance(operational, dict):
                recovery = operational.get("recovery_readiness")
            recovery_available = recovery_statusline_available(recovery)
            failure_label = (
                "任务未就绪"
                if first == "task_lane_bound"
                else "交互未就绪"
            )
            line = (
                f"sulde \033[31m●\033[0m {failure_label}:{first}"
                + ("·恢复可用" if recovery_available else "")
            )
    scheduler_issues = statusline_scheduler_issues(status)
    if scheduler_issues:
        scheduler_label = f"调度降级:{scheduler_issues[0]}"
        if interactive_unready and waiting is None:
            line += f"/{scheduler_label}"
        elif waiting is not None:
            line += f"·{scheduler_label}"
        else:
            line = f"sulde \033[33m●\033[0m 交互可用·{scheduler_label}"
    if status.get("runtime_available") is False:
        line = "sulde \033[31m●\033[0m 运行时不可用"
    if status.get("launcher_contract_healthy") is False:
        recovery = status.get("recovery_readiness")
        line = (
            "sulde \033[31m●\033[0m 接线漂移"
            + (
                "·恢复可用"
                if recovery_statusline_available(recovery)
                else ""
            )
        )
    recovery = status.get("recovery_readiness")
    if not isinstance(recovery, dict) and isinstance(operational, dict):
        recovery = operational.get("recovery_readiness")
    if isinstance(recovery, dict):
        generation_bits = []
        if recovery.get("last_recovery_verified") is True:
            generation_bits.append("上次恢复已验")
        elif recovery.get("status") == "diagnosis_available":
            generation_bits.append("诊断可用·恢复未验")
        if recovery.get("hook_generation_status") == "old":
            generation_bits.append("Hook旧")
        if recovery.get("skill_catalog_restart_required") is True:
            generation_bits.append("Skill重启")
        active = recovery.get("active_run")
        if isinstance(active, dict):
            stage = str(active.get("stage") or active.get("reason") or "")
            if stage:
                generation_bits.append(f"恢复:{stage}")
        if generation_bits:
            line += " " + "/".join(generation_bits)
    suffix = f" 任务:{stalled}滞" if isinstance(stalled, int) and stalled > 0 else ""
    return line[: max(0, 80 - len(suffix))] + suffix


def recovery_statusline_available(recovery: Any) -> bool:
    """Require explicit verified lane truth before claiming recovery readiness."""
    return (
        isinstance(recovery, dict)
        and recovery.get("status") == "ready"
        and recovery.get("lane_available") is True
        and recovery.get("typed_route_available") is True
        and recovery.get("human_confirmation") == "live_verified"
        and recovery.get("repair_execution") == "verified"
        and recovery.get("recovery_verified") is True
    )


def notification_warnings(status: dict[str, Any]) -> list[str]:
    home = status["kb_home"]
    warnings: list[str] = []
    if status.get("launcher_contract_healthy") is False:
        detail = "; ".join(str(issue) for issue in status.get("launcher_contract_issues", [])[:3])
        warnings.append(
            f"稳定接线未同步: {detail or 'launcher contract unavailable'}; "
            "请通过原生 typed recovery card 选择 repair_launcher；"
            "本提示和任何终端命令都不构成授权"
        )
    if status.get("statusline_snapshot_published") is False:
        warnings.append("交互状态快照发布失败；后台状态已观测但新会话将显示降级状态")
    stale = status.get("kb_index_stale")
    if stale is True:
        warnings.append(f"索引过期: {home}/kb.db")
    elif stale is None:
        warnings.append(f"索引状态不可用: {home}/kb.db")
    pending = status.get("mem_pending_embedding")
    if pending is None:
        warnings.append(f"记忆库不可用: {home}/memory.db")
    elif pending > 500:
        warnings.append(f"待嵌积压 {pending}: {home}/memory.db")
    harvest_age = status.get("harvest_age_seconds")
    if harvest_age is None:
        warnings.append(f"收割状态不可用: {home}/codex-harvest-state.json")
    elif harvest_age > DAY_SECONDS:
        warnings.append(f"收割滞后 {relative_age(harvest_age)}: {home}/codex-harvest-state.json")
    capture_age = status.get("mem_last_capture_age_seconds")
    if capture_age is None:
        warnings.append(f"记忆捕获状态不可用: {home}/memory.db")
    elif capture_age > DAY_SECONDS:
        warnings.append(f"记忆捕获静默 {relative_age(capture_age)}: {home}/memory.db")
    life_status = status.get("life_status")
    life_age = status.get("life_age_seconds")
    if life_status is None:
        warnings.append(f"生命周期状态不可用: {home}/life/state.json")
    elif life_status != "ready":
        warnings.append(f"生命周期降级({life_status}): {home}/life/state.json")
    elif status.get("life_evolution_status") != "ready":
        warnings.append(f"器官进化状态异常({status.get('life_evolution_status')}): {home}/evolution/registry.json")
    elif isinstance(life_age, int) and life_age > LIFE_STALE_SECONDS:
        warnings.append(f"生命周期状态滞后 {relative_age(life_age)}: {home}/life/state.json")
    if status.get("runtime_available") is False:
        warnings.append(
            f"调度宿主不可用({status.get('runtime_provider')}): "
            f"{status.get('runtime_executable')}"
        )
    operational = status.get("operational_readiness")
    if isinstance(operational, dict) and operational.get("status") != "ready":
        reasons = operational.get("reasons")
        detail = ",".join(str(item) for item in reasons[:5]) if isinstance(reasons, list) else "unknown"
        scope = str(operational.get("readiness_scope") or "scheduler")
        label = "当前交互未就绪" if scope == "interactive" else "后台调度未就绪"
        warnings.append(f"{label}: {detail}")
    violations = status.get("event_contract_violations")
    if isinstance(violations, int) and violations > 0:
        warnings.append(
            f"事件观察契约违规 {violations} 条；运行 event-observer.py verify 查看来源级证据"
        )
    interventions = status.get("interventions_open")
    if isinstance(interventions, int) and interventions > 0:
        warnings.append(
            f"有 {interventions} 个外部操作结果无法证明；监督 Agent 应读取 interventions，"
            "自动重探测可验证事实，只把无法机器判定的语义选择交给原生 Allow/Deny"
        )
    invalid_interventions = status.get("intervention_invalid_stores")
    if isinstance(invalid_interventions, int) and invalid_interventions > 0:
        warnings.append(
            f"有 {invalid_interventions} 个外部操作状态日志无法重放；禁止自动恢复，"
            "监督 Agent 应保全原日志、生成只读诊断并通过原生界面请求必要裁决"
        )
    blocking_effects = status.get("effect_blocking")
    if (
        isinstance(blocking_effects, int)
        and blocking_effects > 0
        and not (isinstance(interventions, int) and interventions > 0)
    ):
        warnings.append(
            f"有 {blocking_effects} 个外部操作仍在验证/重试屏障中；依赖写入保持阻断"
        )
    try:
        distill_log = Path(home) / "auto-distill.log"
        if not distill_log.is_file():
            warnings.append(f"日蒸馏日志不存在: {distill_log}")
        else:
            distill_age = max(
                0,
                int(datetime.now(timezone.utc).timestamp() - distill_log.stat().st_mtime),
            )
            if distill_age > DISTILL_STALE_SECONDS:
                warnings.append(f"日蒸馏滞后 {relative_age(distill_age)}: {distill_log}")
    except (OSError, ValueError, OverflowError):
        pass
    try:
        sync_config_path = Path(home) / "mem-sync.json"
        sync_config = json.loads(sync_config_path.read_text(encoding="utf-8"))
        sync_projects = sync_config.get("sync_projects") if isinstance(sync_config, dict) else None
        if isinstance(sync_projects, dict) and sync_projects:
            sync_state = Path(home) / "mem-sync-state.json"
            if not sync_state.is_file():
                warnings.append(f"记忆导出状态不存在: {sync_state}")
            else:
                sync_age = max(
                    0,
                    int(datetime.now(timezone.utc).timestamp() - sync_state.stat().st_mtime),
                )
                if sync_age > DAY_SECONDS:
                    warnings.append(f"记忆导出滞后 {relative_age(sync_age)}: {sync_state}")
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, OverflowError):
        pass
    return warnings


def notify(status: dict[str, Any]) -> None:
    if os.environ.get("SULDE_NOTIFY", "").lower() == "off":
        return
    warnings = notification_warnings(status)
    if not warnings:
        return
    for warning in warnings:
        print(f"⚠ {warning}")
    try:
        sys.path.insert(0, str(ROOT / "hooks" / "lib"))
        import kb_notify

        kb_notify.run({"message": "sulde: " + "; ".join(warnings)})
    except Exception:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--statusline", action="store_true")
    modes.add_argument("--json", action="store_true")
    modes.add_argument("--notify", action="store_true")
    parser.add_argument("--read-only", action="store_true", help="collect without publishing a snapshot")
    parser.add_argument("--home", type=Path, help="explicit observation data root")
    args = parser.parse_args()
    if args.home is not None:
        os.environ["SULDE_KB_HOME"] = str(args.home.expanduser())
    if args.statusline:
        snapshot = read_statusline_snapshot(kb_home())
        line = snapshot["line"]
        if snapshot.get("snapshot_status") != "fresh":
            line = f"{line} 快照过期"
        print(line)
        return (
            0
            if snapshot.get("snapshot_status") == "fresh" and snapshot["healthy"]
            else 1
        )
    exit_code = 2
    try:
        status = collect()
        line = statusline(status)
        snapshot_published = False if args.read_only else write_statusline_snapshot(
            Path(str(status.get("kb_home") or kb_home())),
            line=line,
            healthy=statusline_healthy(status),
        )
        status["statusline_snapshot_published"] = snapshot_published
        if args.json:
            print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        else:
            notify(status)
        # The hourly observer reports degradation in its payload/notification;
        # successfully observing a warning is not a process failure.  Returning
        # one here makes the observer poison scheduler readiness on its next run.
        exit_code = (
            0
            if args.notify
            else 0
            if status.get("ok") is True and snapshot_published
            else 1
        )
    except Exception:
        if args.json:
            print(json.dumps({"ok": False, "warn": True, "fleet_running": 0, "fleet_stalled": 0}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
