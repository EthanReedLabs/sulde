#!/usr/bin/env python3
"""Versioned, sealed and task-lane-independent recovery control plane."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Callable, Mapping

from supervisor_state import (
    SupervisorState,
    SupervisorStateError,
    exact_object,
    exact_text,
    require_plain_json,
)

PROTOCOL_SCHEMA = "sulde-recovery-lane-v1"
CAPABILITY_SCHEMA = "sulde-recovery-capability-v1"
REQUEST_SCHEMA = "sulde-recovery-request-v1"
ROUTE_SCHEMA = "sulde-recovery-route-v1"
CARD_SCHEMA = "sulde-recovery-card-v1"
UI_RESULT_SCHEMA = "sulde-recovery-ui-result-v1"
DECISION_SCHEMA = "sulde-recovery-human-decision-v1"
RESULT_SCHEMA = "sulde-recovery-result-v1"
STATUS_SCHEMA = "sulde-recovery-status-v1"
DOCTOR_SCHEMA = "sulde-recovery-doctor-v1"
RUN_STATUS_SCHEMA = "sulde-recovery-run-status-v1"
LOG_SCHEMA = "sulde-recovery-log-event-v1"
VERIFIER_RECEIPT_SCHEMA = "sulde-recovery-verifier-receipt-v1"
ADAPTER_RESULT_SCHEMA = "sulde-recovery-adapter-result-v1"
EXECUTION_REQUEST_SCHEMA = "sulde-recovery-execution-request-v1"
SUPERVISOR_EVENT_SCHEMA = "sulde-recovery-supervisor-event-v1"
SILENT_STATUS_SECONDS = 5.0
PROGRESS_WINDOW_SECONDS = 30.0
MAX_DISPATCH_ATTEMPTS = 2
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "blocked"})
UI_OUTCOMES = frozenset({"allow", "deny", "inspect_diff", "later"})
READ_ACTIONS = frozenset({"status", "doctor", "readback"})

# No generic shell, patch or delete route exists.
ROUTE_SPECS: dict[str, dict[str, Any]] = {
    "status": {"effect": "read", "method": None, "allowed_changes": ()},
    "doctor": {"effect": "read", "method": None, "allowed_changes": ()},
    "readback": {"effect": "read", "method": None, "allowed_changes": ()},
    "settle": {
        "effect": "local_write", "method": "settle_transaction",
        "allowed_changes": ("append_exact_settlement", "isolate_derived_debt"),
    },
    "abort": {
        "effect": "local_write", "method": "abort_transaction",
        "allowed_changes": ("append_exact_abort", "isolate_derived_debt"),
    },
    "repair_launcher": {
        "effect": "local_write", "method": "repair_launcher",
        "allowed_changes": ("replace_exact_launcher_entry", "preserve_static_catalog"),
    },
    "repair_generated_bytecode": {
        "effect": "local_write", "method": "repair_generated_bytecode",
        "allowed_changes": ("replace_exact_generated_bytecode", "preserve_sources"),
    },
    "uninstall": {
        "effect": "destructive", "method": "uninstall",
        "allowed_changes": ("remove_exact_installation_generation", "preserve_audit"),
    },
    "rollback": {
        "effect": "local_write", "method": "rollback",
        "allowed_changes": ("restore_exact_prior_generation", "preserve_audit"),
    },
}
_CAPABILITY_FIELDS = frozenset({
    "schema", "version", "provider", "session_id", "workspace",
    "installed_generation", "action", "target_identity", "expected_pre_state",
    "allowed_changes", "issued_at", "expires_at", "verifier", "nonce",
    "capability_id", "seal_sha256",
})
_REQUEST_FIELDS = frozenset({
    "schema", "provider", "session_id", "workspace", "installed_generation",
    "action", "target_identity", "capability",
})
_ADAPTER_RESULT_FIELDS = frozenset({
    "schema", "run_id", "effect_id", "adapter_identity", "action",
    "target_identity", "status", "observed_post_state", "detail",
})
_VERIFIER_RECEIPT_FIELDS = frozenset({
    "schema", "receipt_id", "verifier_identity", "run_id", "effect_id",
    "action", "target_identity", "result_identity", "status", "evidence",
})
_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
_WAITING = re.compile(
    r"^\s*(?:waiting for agents|poll(?:ing)?(?:\s+#?\d+)?)\s*[.。…]*\s*$",
    re.I,
)


class RecoveryLaneError(SupervisorStateError):
    """Recovery input or durable state failed closed."""


def _number(value: Any, name: str) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise RecoveryLaneError(f"{name} must be an exact finite number")
    selected = float(value)
    if not math.isfinite(selected) or selected < 0:
        raise RecoveryLaneError(f"{name} must be finite and non-negative")
    return selected


def _sha(value: Any, name: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise RecoveryLaneError(f"{name} must be sha256:<64 lowercase hex>")
    return value


def _canonical(value: Any) -> bytes:
    require_plain_json(value, name="sealed value")
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _plain_digest(domain: str, value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        domain.encode("utf-8") + b"\0" + _canonical(value)
    ).hexdigest()


def _seal(key: bytes, value: Any) -> str:
    return "sha256:" + hmac.new(key, _canonical(value), hashlib.sha256).hexdigest()


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if type(value) is list:
        return tuple(_freeze(child) for child in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(child) for key, child in value.items()}
    if type(value) is tuple:
        return [_thaw(child) for child in value]
    return deepcopy(value)


def _workspace(value: Any) -> str:
    selected = exact_text(value, name="workspace")
    if not os.path.isabs(selected):
        raise RecoveryLaneError("workspace must be absolute")
    normalized = os.path.abspath(selected)
    if normalized != selected or selected in {os.path.sep, str(Path.home())}:
        raise RecoveryLaneError("workspace must be normalized and narrowly scoped")
    return selected


def _identity(value: Any, name: str) -> str:
    selected = exact_text(value, name=name)
    if len(selected) > 512 or any(ord(char) < 32 for char in selected):
        raise RecoveryLaneError(f"{name} is unsafe or too long")
    return selected


@dataclass(frozen=True)
class RecoveryCapability:
    """Immutable view of one HMAC-sealed recovery capability."""

    schema: str
    version: int
    provider: str
    session_id: str
    workspace: str
    installed_generation: str
    action: str
    target_identity: str
    expected_pre_state: Mapping[str, Any]
    allowed_changes: tuple[str, ...]
    issued_at: float
    expires_at: float
    verifier: Mapping[str, Any]
    nonce: str
    capability_id: str
    seal_sha256: str

    @classmethod
    def from_dict(cls, value: Any) -> "RecoveryCapability":
        item = exact_object(value, name="recovery capability", fields=_CAPABILITY_FIELDS)
        expected = exact_object(item["expected_pre_state"], name="expected_pre_state")
        verifier = exact_object(item["verifier"], name="verifier")
        changes = item["allowed_changes"]
        if type(changes) is not list or any(type(change) is not str for change in changes):
            raise RecoveryLaneError("allowed_changes must be an exact string list")
        return cls(
            schema=item["schema"], version=item["version"],
            provider=item["provider"], session_id=item["session_id"],
            workspace=item["workspace"], installed_generation=item["installed_generation"],
            action=item["action"], target_identity=item["target_identity"],
            expected_pre_state=_freeze(deepcopy(expected)),
            allowed_changes=tuple(changes), issued_at=item["issued_at"],
            expires_at=item["expires_at"], verifier=_freeze(deepcopy(verifier)),
            nonce=item["nonce"], capability_id=item["capability_id"],
            seal_sha256=item["seal_sha256"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "version": self.version,
            "provider": self.provider, "session_id": self.session_id,
            "workspace": self.workspace,
            "installed_generation": self.installed_generation,
            "action": self.action, "target_identity": self.target_identity,
            "expected_pre_state": _thaw(self.expected_pre_state),
            "allowed_changes": list(self.allowed_changes),
            "issued_at": self.issued_at, "expires_at": self.expires_at,
            "verifier": _thaw(self.verifier), "nonce": self.nonce,
            "capability_id": self.capability_id, "seal_sha256": self.seal_sha256,
        }


def _capability_material(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(child) for key, child in value.items()
        if key not in {"capability_id", "seal_sha256"}
    }


def _validate_capability_shape(capability: RecoveryCapability) -> None:
    item = capability.to_dict()
    if item["schema"] != CAPABILITY_SCHEMA or type(item["version"]) is not int or item["version"] != 1:
        raise RecoveryLaneError("recovery capability schema/version is invalid")
    exact_text(item["provider"], name="provider")
    if len(exact_text(item["session_id"], name="session_id")) > 256:
        raise RecoveryLaneError("session_id is too long")
    _workspace(item["workspace"])
    _identity(item["installed_generation"], "installed_generation")
    if item["action"] not in ROUTE_SPECS:
        raise RecoveryLaneError("unknown recovery action")
    _identity(item["target_identity"], "target_identity")
    require_plain_json(item["expected_pre_state"], name="expected_pre_state")
    if tuple(item["allowed_changes"]) != ROUTE_SPECS[item["action"]]["allowed_changes"]:
        raise RecoveryLaneError("recovery action change set is wider or substituted")
    issued = _number(item["issued_at"], "issued_at")
    expires = _number(item["expires_at"], "expires_at")
    if issued >= expires:
        raise RecoveryLaneError("capability expiry must follow issuance")
    verifier = exact_object(item["verifier"], name="verifier")
    if frozenset(verifier) != frozenset({"identity", "kind"}):
        raise RecoveryLaneError("verifier binding fields are invalid")
    _sha(verifier["identity"], "verifier.identity")
    if verifier["kind"] != "independent_readback":
        raise RecoveryLaneError("verifier must be independent readback")
    _identity(item["nonce"], "nonce")
    _sha(item["capability_id"], "capability_id")
    _sha(item["seal_sha256"], "seal_sha256")


def _validate_adapter_result(value: Any) -> dict[str, Any]:
    item = deepcopy(exact_object(
        value, name="recovery adapter result", fields=_ADAPTER_RESULT_FIELDS
    ))
    if item["schema"] != ADAPTER_RESULT_SCHEMA:
        raise RecoveryLaneError("recovery adapter result schema is invalid")
    for field in ("run_id", "effect_id", "adapter_identity"):
        _sha(item[field], field)
    if item["action"] not in ROUTE_SPECS:
        raise RecoveryLaneError("adapter returned an unknown recovery action")
    _identity(item["target_identity"], "target_identity")
    if item["status"] not in {"completed", "failed", "unknown"}:
        raise RecoveryLaneError("recovery adapter result status is invalid")
    exact_object(item["observed_post_state"], name="observed_post_state")
    exact_object(item["detail"], name="adapter result detail")
    return item


def _validate_verifier_receipt(value: Any) -> dict[str, Any]:
    item = deepcopy(exact_object(
        value, name="recovery verifier receipt", fields=_VERIFIER_RECEIPT_FIELDS
    ))
    if item["schema"] != VERIFIER_RECEIPT_SCHEMA:
        raise RecoveryLaneError("recovery verifier receipt schema is invalid")
    for field in (
        "receipt_id", "verifier_identity", "run_id", "effect_id",
        "result_identity",
    ):
        _sha(item[field], field)
    if item["action"] not in ROUTE_SPECS:
        raise RecoveryLaneError("verifier returned an unknown recovery action")
    _identity(item["target_identity"], "target_identity")
    if item["status"] not in {"passed", "failed", "unknown", "contradictory"}:
        raise RecoveryLaneError("recovery verifier status is invalid")
    exact_object(item["evidence"], name="verifier evidence")
    return item


def _has_unquoted_shell_control(command: str) -> bool:
    quote = ""
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = ""
        elif char in {"'", '"'}:
            quote = char
        elif char in ";|&<>\n\r" or ord(char) == 96:
            return True
        elif char == "$" and index + 1 < len(command) and command[index + 1] == "(":
            return True
        index += 1
    return bool(quote or escaped)


def classify_trusted_control_command(command: Any, *, trusted: bool) -> dict[str, Any]:
    """Separate trusted-call shape violations from destructive semantics."""
    if type(command) is not str or not command.strip():
        return {"classification": "not_recovery", "trusted": trusted}
    if trusted and _has_unquoted_shell_control(command):
        return {
            "classification": "invalid_composition", "trusted": True,
            "decision": "deny", "launch": False, "pause": False,
            "effect_debt": False,
        }
    return {
        "classification": "trusted_control" if trusted else "untrusted_lookalike",
        "trusted": trusted,
    }


class RecoveryLane:
    """Narrow recovery router independent from ordinary lane readiness."""

    def __init__(
        self, state_path: str, *, seal_key: bytes,
        wall_clock: Callable[[], float], monotonic_clock: Callable[[], float],
        trusted_adapter: Any = None, trusted_verifier: Any = None,
        verifier_identity: str | None = None,
        adapter_identity: str | None = None, supervisor: Any = None,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        if type(seal_key) is not bytes or len(seal_key) < 32:
            raise RecoveryLaneError("seal_key must contain at least 32 bytes")
        self.state = SupervisorState(state_path)
        self._seal_key = seal_key
        self.wall_clock = wall_clock
        self.monotonic_clock = monotonic_clock
        self.trusted_adapter = trusted_adapter
        self.trusted_verifier = trusted_verifier
        self.verifier_identity = (
            _sha(verifier_identity, "verifier_identity")
            if verifier_identity is not None else None
        )
        self.adapter_identity = (
            _sha(adapter_identity, "adapter_identity")
            if adapter_identity is not None else None
        )
        if trusted_adapter is not None and trusted_adapter is trusted_verifier:
            raise RecoveryLaneError("adapter and independent verifier must be distinct")
        if trusted_adapter is not None and self.adapter_identity is None:
            raise RecoveryLaneError("trusted adapter identity is required")
        self.supervisor = supervisor
        self._failpoint = failpoint or (lambda _boundary: None)

    def _now(self) -> tuple[float, float]:
        return (
            _number(self.wall_clock(), "wall_clock"),
            _number(self.monotonic_clock(), "monotonic_clock"),
        )

    def _events(self) -> list[dict[str, Any]]:
        return self.state.snapshot()["events"]

    def _payloads(self, event_type: str) -> list[dict[str, Any]]:
        return [
            event["payload"] for event in self._events()
            if event["event_type"] == event_type
        ]

    def issue_capability(
        self, *, provider: str, session_id: str, workspace: str,
        installed_generation: str, action: str, target_identity: str,
        expected_pre_state: dict[str, Any], expires_at: float,
        verifier_identity: str, nonce: str,
    ) -> RecoveryCapability:
        if action not in ROUTE_SPECS:
            raise RecoveryLaneError("unknown recovery action")
        wall, _mono = self._now()
        material = {
            "schema": CAPABILITY_SCHEMA, "version": 1,
            "provider": exact_text(provider, name="provider"),
            "session_id": exact_text(session_id, name="session_id"),
            "workspace": _workspace(workspace),
            "installed_generation": _identity(installed_generation, "installed_generation"),
            "action": action,
            "target_identity": _identity(target_identity, "target_identity"),
            "expected_pre_state": deepcopy(exact_object(
                expected_pre_state, name="expected_pre_state"
            )),
            "allowed_changes": list(ROUTE_SPECS[action]["allowed_changes"]),
            "issued_at": wall, "expires_at": _number(expires_at, "expires_at"),
            "verifier": {
                "identity": _sha(verifier_identity, "verifier_identity"),
                "kind": "independent_readback",
            },
            "nonce": _identity(nonce, "nonce"),
        }
        capability_id = _plain_digest("recovery-capability", material)
        value = {
            **material, "capability_id": capability_id,
            "seal_sha256": _seal(
                self._seal_key, {**material, "capability_id": capability_id}
            ),
        }
        capability = RecoveryCapability.from_dict(value)
        _validate_capability_shape(capability)
        return capability

    def validate_capability(
        self, value: Any, *, provider: str, session_id: str, workspace: str,
        installed_generation: str, action: str, target_identity: str,
        current_pre_state: dict[str, Any], now: float | None = None,
        require_unused: bool = True,
    ) -> RecoveryCapability:
        capability = (
            value if isinstance(value, RecoveryCapability)
            else RecoveryCapability.from_dict(value)
        )
        _validate_capability_shape(capability)
        item = capability.to_dict()
        material = _capability_material(item)
        expected_id = _plain_digest("recovery-capability", material)
        if (
            not hmac.compare_digest(item["capability_id"], expected_id)
            or not hmac.compare_digest(
                item["seal_sha256"],
                _seal(self._seal_key, {**material, "capability_id": expected_id}),
            )
        ):
            raise RecoveryLaneError("recovery capability seal was forged")
        bound = (
            item["provider"], item["session_id"], item["workspace"],
            item["installed_generation"], item["action"], item["target_identity"],
        )
        current = (
            provider, session_id, _workspace(workspace), installed_generation,
            action, target_identity,
        )
        if any(type(part) is not str for part in current) or bound != current:
            raise RecoveryLaneError(
                "provider/session/workspace/generation/action/target drift"
            )
        selected_now = self.wall_clock() if now is None else now
        checked_now = _number(selected_now, "now")
        if checked_now < item["issued_at"]:
            raise RecoveryLaneError("recovery capability was issued in the future")
        if checked_now >= item["expires_at"]:
            raise RecoveryLaneError("recovery capability expired")
        current_state = deepcopy(exact_object(
            current_pre_state, name="current_pre_state"
        ))
        if current_state != item["expected_pre_state"]:
            raise RecoveryLaneError("expected pre-state drifted")
        if require_unused and any(
            row.get("capability_id") == item["capability_id"]
            for row in self._payloads("capability_consumed")
        ):
            raise RecoveryLaneError("recovery capability replay refused")
        return capability

    @staticmethod
    def request(capability: RecoveryCapability) -> dict[str, Any]:
        item = capability.to_dict()
        return {
            "schema": REQUEST_SCHEMA, "provider": item["provider"],
            "session_id": item["session_id"], "workspace": item["workspace"],
            "installed_generation": item["installed_generation"],
            "action": item["action"], "target_identity": item["target_identity"],
            "capability": item,
        }

    def classify_request(
        self, request: Any, *, current_pre_state: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            item = exact_object(
                request, name="recovery request", fields=_REQUEST_FIELDS
            )
            if item["schema"] != REQUEST_SCHEMA:
                raise RecoveryLaneError("recovery request schema is invalid")
            capability = self.validate_capability(
                item["capability"], provider=item["provider"],
                session_id=item["session_id"], workspace=item["workspace"],
                installed_generation=item["installed_generation"],
                action=item["action"], target_identity=item["target_identity"],
                current_pre_state=current_pre_state,
            )
            spec = ROUTE_SPECS[capability.action]
            return {
                "schema": ROUTE_SCHEMA, "status": "recovery_classified",
                "action": capability.action, "effect": spec["effect"],
                "target_identity": capability.target_identity,
                "capability_id": capability.capability_id,
                "ordinary_pretool_policy_required": False,
                "task_lane_binding_required": False,
            }
        except (RecoveryLaneError, SupervisorStateError, KeyError, TypeError) as error:
            return {
                "schema": ROUTE_SCHEMA, "status": "denied", "reason": str(error),
                "ordinary_pretool_policy_required": False,
                "task_lane_binding_required": False, "launch": False,
            }

    def pretool_decision(
        self, event: Any, *, current_pre_state: dict[str, Any],
        ordinary_guard: Callable[[Any], dict[str, Any]],
    ) -> dict[str, Any]:
        """Route typed recovery before invoking the possibly broken guard."""
        if isinstance(event, dict) and event.get("schema") == REQUEST_SCHEMA:
            route = self.classify_request(
                event, current_pre_state=current_pre_state
            )
            if route["status"] == "recovery_classified":
                decisions = [
                    row for row in self._payloads("human_decision_recorded")
                    if row.get("capability_id") == route["capability_id"]
                ]
                allowed = bool(decisions and decisions[-1].get("outcome") == "allow")
                if ROUTE_SPECS[route["action"]]["effect"] == "read" or allowed:
                    return {
                        **route, "decision": "allow_recovery",
                        "default_policy_recheck_required": False, "launch": True,
                    }
                return {
                    **route, "decision": "permission_required", "launch": False,
                    "card": self.recovery_card(event["capability"]),
                }
            return {
                **route, "decision": "deny", "pause": False, "effect_debt": False,
            }
        command = event.get("command") if isinstance(event, dict) else None
        trusted = bool(event.get("trusted_recovery_control")) if isinstance(event, dict) else False
        shape = classify_trusted_control_command(command, trusted=trusted)
        if shape["classification"] == "invalid_composition":
            return {
                "schema": ROUTE_SCHEMA, **shape,
                "reason": "invalid trusted control composition",
            }
        return ordinary_guard(event)

    def recovery_card(self, capability: Any) -> dict[str, Any]:
        selected = (
            capability if isinstance(capability, RecoveryCapability)
            else RecoveryCapability.from_dict(capability)
        )
        _validate_capability_shape(selected)
        card = {
            "schema": CARD_SCHEMA, "capability_id": selected.capability_id,
            "provider": selected.provider, "session_id": selected.session_id,
            "workspace": selected.workspace, "action": selected.action,
            "target_identity": selected.target_identity,
            "installed_generation": selected.installed_generation,
            "expected_pre_state": _thaw(selected.expected_pre_state),
            "allowed_changes": list(selected.allowed_changes),
            "expires_at": selected.expires_at, "verifier": _thaw(selected.verifier),
            "title": "Sulde recovery request",
            "summary": f"{selected.action} -> {selected.target_identity}",
            "choices": [
                {"outcome": "allow", "label": "Allow"},
                {"outcome": "deny", "label": "Deny"},
                {"outcome": "inspect_diff", "label": "查看差异"},
                {"outcome": "later", "label": "稍后"},
            ],
            "authority": "native_typed_callback_only",
            "text_response_authoritative": False,
        }
        card["card_id"] = _seal(
            self._seal_key, {"domain": "recovery-card", "card": card}
        )
        return card

    def request_permission(self, capability: Any, host: Any) -> dict[str, Any]:
        selected = (
            capability if isinstance(capability, RecoveryCapability)
            else RecoveryCapability.from_dict(capability)
        )
        card = self.recovery_card(selected)
        self.state.append(
            "recovery_card_published",
            {
                "schema": LOG_SCHEMA,
                "event_id": _plain_digest("card-published", card),
                "capability_id": selected.capability_id, "card": card,
                "observed_at": self.wall_clock(),
            },
            unique_fields=("capability_id",),
        )
        try:
            callback = host.permission_request(deepcopy(card))
        except Exception as error:
            return {
                "schema": UI_RESULT_SCHEMA, "status": "unavailable",
                "reason": type(error).__name__,
                "capability_id": selected.capability_id,
                "ordinary_lane_required": False,
                "independent_path": {
                    "schema": ROUTE_SCHEMA, "kind": "native_recovery_decision",
                    "card_id": card["card_id"],
                    "capability_id": selected.capability_id,
                    "ordinary_pretool_policy_required": False,
                    "authority": "native_typed_callback_only",
                },
            }
        try:
            decision = exact_object(callback, name="native recovery callback")
            required = frozenset({
                "schema", "card_id", "capability_id", "provider", "session_id",
                "outcome", "decided_at", "authority", "channel", "receipt_id",
            })
            if frozenset(decision) != required or decision["schema"] != DECISION_SCHEMA:
                raise RecoveryLaneError("native recovery callback schema is invalid")
            if decision["outcome"] not in UI_OUTCOMES:
                raise RecoveryLaneError("native recovery callback outcome is invalid")
            expected = {
                "card_id": card["card_id"],
                "capability_id": selected.capability_id,
                "provider": selected.provider, "session_id": selected.session_id,
                "authority": "human", "channel": "native_typed_receipt",
            }
            if any(decision[field] != value for field, value in expected.items()):
                raise RecoveryLaneError(
                    "native recovery callback is foreign or non-authoritative"
                )
            _identity(decision["receipt_id"], "receipt_id")
            decided_at = _number(decision["decided_at"], "decided_at")
            if (
                decided_at < selected.issued_at
                or decided_at >= selected.expires_at
                or decided_at > _number(self.wall_clock(), "wall_clock")
            ):
                raise RecoveryLaneError("native recovery callback time is invalid")
            prior = [
                row for row in self._payloads("human_decision_recorded")
                if row.get("capability_id") == selected.capability_id
            ]
            if prior:
                if prior[-1] != decision:
                    raise RecoveryLaneError(
                        "one recovery card has conflicting callbacks"
                    )
                return {
                    "schema": UI_RESULT_SCHEMA, "status": "duplicate",
                    "decision": prior[-1],
                }
            self.state.append(
                "human_decision_recorded", deepcopy(decision),
                unique_fields=("capability_id",),
            )
            return {
                "schema": UI_RESULT_SCHEMA,
                "status": "authorized" if decision["outcome"] == "allow" else "observed",
                "decision": deepcopy(decision), "text_fallback_used": False,
            }
        except (RecoveryLaneError, SupervisorStateError, KeyError, TypeError) as error:
            return {
                "schema": UI_RESULT_SCHEMA, "status": "denied",
                "reason": str(error), "capability_id": selected.capability_id,
                "text_fallback_used": False,
            }

    def _prepared(self, capability_id: str) -> dict[str, Any] | None:
        rows = [
            row for row in self._payloads("recovery_run_prepared")
            if row.get("capability_id") == capability_id
        ]
        if len(rows) > 1:
            raise RecoveryLaneError("capability has ambiguous prepared runs")
        return deepcopy(rows[0]) if rows else None

    def _terminal_for(self, run_id: str) -> dict[str, Any] | None:
        rows = [
            row for row in self._payloads("recovery_terminal_recorded")
            if row.get("run_id") == run_id
        ]
        if len(rows) > 1:
            raise RecoveryLaneError("recovery run has ambiguous terminal results")
        return deepcopy(rows[0]) if rows else None

    def _publish_supervisor(self, kind: str, payload: dict[str, Any]) -> None:
        if self.supervisor is None:
            return
        recorder = getattr(self.supervisor, "record_recovery_event", None)
        if not callable(recorder):
            raise RecoveryLaneError("H03 supervisor recovery bridge is unavailable")
        recorder({
            "schema": SUPERVISOR_EVENT_SCHEMA,
            "kind": kind,
            "payload": deepcopy(payload),
        })

    def _record_terminal(
        self, prepared: dict[str, Any], status: str, reason: str,
        *, result: dict[str, Any],
    ) -> dict[str, Any]:
        if status not in TERMINAL_STATES:
            raise RecoveryLaneError("terminal recovery status is invalid")
        existing = self._terminal_for(prepared["run_id"])
        if existing is not None:
            return existing
        wall, mono = self._now()
        terminal = {
            "schema": RESULT_SCHEMA,
            "run_id": prepared["run_id"],
            "capability_id": prepared["capability_id"],
            "action": prepared["action"],
            "target_identity": prepared["target_identity"],
            "status": status,
            "reason": _identity(reason, "terminal reason"),
            "result": deepcopy(exact_object(result, name="terminal result")),
            "observed_wall": wall,
            "observed_mono": mono,
        }
        self.state.append(
            "recovery_terminal_recorded", terminal, unique_fields=("run_id",)
        )
        self._publish_supervisor("terminal", terminal)
        return terminal

    def record_progress(
        self, run_id: str, *, stage: str, message: str,
    ) -> dict[str, Any]:
        selected_run = _sha(run_id, "run_id")
        selected_stage = _identity(stage, "stage")
        selected_message = _identity(message, "message")
        if self._terminal_for(selected_run) is not None:
            return {"status": "terminal", "run_id": selected_run}
        prepared = [
            row for row in self._payloads("recovery_run_prepared")
            if row.get("run_id") == selected_run
        ]
        if len(prepared) != 1:
            raise RecoveryLaneError("progress run is not uniquely prepared")
        prior = [
            row for row in self._payloads("recovery_progress_recorded")
            if row.get("run_id") == selected_run
        ]
        duplicate = bool(
            prior
            and prior[-1]["stage"] == selected_stage
            and prior[-1]["message"] == selected_message
        )
        if duplicate:
            return {
                "status": "suppressed_duplicate",
                "run_id": selected_run,
                "waiting_suppressed": bool(_WAITING.fullmatch(selected_message)),
            }
        wall, mono = self._now()
        sequence = len(prior) + 1
        event = {
            "schema": LOG_SCHEMA,
            "event_id": _plain_digest("recovery-progress", {
                "run_id": selected_run, "sequence": sequence,
                "stage": selected_stage, "message": selected_message,
            }),
            "run_id": selected_run,
            "stage_id": _plain_digest("recovery-stage", {
                "run_id": selected_run, "stage": selected_stage,
            }),
            "stage": selected_stage,
            "message": selected_message,
            "sequence": sequence,
            "observed_wall": wall,
            "observed_mono": mono,
        }
        self.state.append(
            "recovery_progress_recorded", event, unique_fields=("event_id",)
        )
        self._publish_supervisor("progress", event)
        return {"status": "recorded", "event": event}

    def tick(self, run_id: str) -> dict[str, Any]:
        selected_run = _sha(run_id, "run_id")
        terminal = self._terminal_for(selected_run)
        if terminal is not None:
            return {"status": "terminal", "terminal": terminal, "changed": []}
        prepared = [
            row for row in self._payloads("recovery_run_prepared")
            if row.get("run_id") == selected_run
        ]
        if len(prepared) != 1:
            raise RecoveryLaneError("status run is not uniquely prepared")
        progress = [
            row for row in self._payloads("recovery_progress_recorded")
            if row.get("run_id") == selected_run
        ]
        anchor = progress[-1] if progress else prepared[0]
        anchor_id = anchor.get("event_id") or prepared[0]["run_id"]
        _wall, mono = self._now()
        elapsed = max(0.0, mono - float(anchor["observed_mono"]))
        projected = [
            row for row in self._payloads("recovery_status_projected")
            if row.get("run_id") == selected_run
        ]
        keys = {(row["kind"], row["window"], row["anchor_id"]) for row in projected}
        changed: list[dict[str, Any]] = []
        if elapsed >= SILENT_STATUS_SECONDS:
            key = ("visible_no_progress", 0, anchor_id)
            if key not in keys:
                changed.append({
                    "schema": RUN_STATUS_SCHEMA,
                    "status_id": _plain_digest("recovery-status", {
                        "run_id": selected_run, "kind": key[0],
                        "window": key[1], "anchor_id": anchor_id,
                    }),
                    "run_id": selected_run, "kind": key[0], "window": key[1],
                    "anchor_id": anchor_id, "reason": "no_visible_progress_5s",
                    "observed_mono": mono,
                })
        window = int(elapsed // PROGRESS_WINDOW_SECONDS)
        if window >= 1:
            key = ("typed_stalled_reason", window, anchor_id)
            if key not in keys:
                changed.append({
                    "schema": RUN_STATUS_SCHEMA,
                    "status_id": _plain_digest("recovery-status", {
                        "run_id": selected_run, "kind": key[0],
                        "window": key[1], "anchor_id": anchor_id,
                    }),
                    "run_id": selected_run, "kind": key[0], "window": key[1],
                    "anchor_id": anchor_id, "reason": "stalled_no_progress",
                    "observed_mono": mono,
                })
        for row in changed:
            self.state.append(
                "recovery_status_projected", row, unique_fields=("status_id",)
            )
            self._publish_supervisor("status", row)
        return {
            "schema": RUN_STATUS_SCHEMA,
            "status": "active",
            "run_id": selected_run,
            "elapsed_without_progress": elapsed,
            "changed": changed,
        }

    def run_status(self, run_id: str) -> dict[str, Any]:
        selected_run = _sha(run_id, "run_id")
        terminal = self._terminal_for(selected_run)
        progress = [
            row for row in self._payloads("recovery_progress_recorded")
            if row.get("run_id") == selected_run
        ]
        starts = [
            row for row in self._payloads("recovery_dispatch_started")
            if row.get("run_id") == selected_run
        ]
        return {
            "schema": RUN_STATUS_SCHEMA,
            "run_id": selected_run,
            "status": terminal["status"] if terminal else "active",
            "terminal": terminal,
            "last_stage": deepcopy(progress[-1]) if progress else None,
            "dispatch_attempts": len(starts),
            "max_dispatch_attempts": MAX_DISPATCH_ATTEMPTS,
            "log_path": str(self.state.path),
        }

    def status(self) -> dict[str, Any]:
        prepared = self._payloads("recovery_run_prepared")
        runs = [self.run_status(row["run_id"]) for row in prepared]
        return {
            "schema": STATUS_SCHEMA,
            "status": "available",
            "ordinary_task_lane_required": False,
            "available_actions": sorted(ROUTE_SPECS),
            "runs": runs,
            "journal_sequence": self.state.snapshot()["sequence"],
            "log_path": str(self.state.path),
        }

    def doctor(
        self, *, task_lane_state: str, launcher_status: str,
        snapshot_status: str, hook_generation_status: str,
        skill_catalog_status: str,
    ) -> dict[str, Any]:
        return {
            "schema": DOCTOR_SCHEMA,
            "status": "diagnosis_available",
            "recovery_lane_available": True,
            "ordinary_task_lane_required": False,
            "task_lane_state": _identity(task_lane_state, "task_lane_state"),
            "launcher_status": _identity(launcher_status, "launcher_status"),
            "snapshot_status": _identity(snapshot_status, "snapshot_status"),
            "hook_generation_status": _identity(
                hook_generation_status, "hook_generation_status"
            ),
            "skill_catalog_status": _identity(
                skill_catalog_status, "skill_catalog_status"
            ),
            "hook_hot_rebind_supported": False,
            "human_confirmation": "unobserved",
            "repair_execution": "configured" if (
                self.trusted_adapter is not None and self.trusted_verifier is not None
            ) else "unavailable",
            "recovery_verified": False,
            "skill_catalog_restart_required": skill_catalog_status != "current",
        }

    def execute(
        self, capability: Any, *, current_pre_state: dict[str, Any],
    ) -> dict[str, Any]:
        selected = (
            capability if isinstance(capability, RecoveryCapability)
            else RecoveryCapability.from_dict(capability)
        )
        _validate_capability_shape(selected)
        prepared = self._prepared(selected.capability_id)
        validation_state = (
            _thaw(selected.expected_pre_state)
            if prepared is not None else current_pre_state
        )
        self.validate_capability(
            selected,
            provider=selected.provider, session_id=selected.session_id,
            workspace=selected.workspace,
            installed_generation=selected.installed_generation,
            action=selected.action, target_identity=selected.target_identity,
            current_pre_state=validation_state,
            require_unused=prepared is None,
        )
        spec = ROUTE_SPECS[selected.action]
        if spec["effect"] != "read":
            decisions = [
                row for row in self._payloads("human_decision_recorded")
                if row.get("capability_id") == selected.capability_id
            ]
            if not decisions or decisions[-1].get("outcome") != "allow":
                raise RecoveryLaneError("exact native Allow is required")
            if (
                self.trusted_adapter is None
                or self.adapter_identity is None
                or self.trusted_verifier is None
                or self.verifier_identity != selected.verifier["identity"]
            ):
                raise RecoveryLaneError("trusted adapter/verifier boundary is unavailable")
        if prepared is None:
            wall, mono = self._now()
            run_id = _plain_digest("recovery-run", {
                "capability_id": selected.capability_id,
                "action": selected.action,
                "target_identity": selected.target_identity,
            })
            prepared = {
                "schema": PROTOCOL_SCHEMA,
                "run_id": run_id,
                "effect_id": _seal(self._seal_key, {
                    "domain": "recovery-effect", "run_id": run_id,
                    "capability_id": selected.capability_id,
                }),
                "capability_id": selected.capability_id,
                "provider": selected.provider,
                "session_id": selected.session_id,
                "workspace": selected.workspace,
                "installed_generation": selected.installed_generation,
                "action": selected.action,
                "target_identity": selected.target_identity,
                "expected_pre_state": _thaw(selected.expected_pre_state),
                "allowed_changes": list(selected.allowed_changes),
                "adapter_identity": self.adapter_identity,
                "verifier_identity": selected.verifier["identity"],
                "observed_wall": wall,
                "observed_mono": mono,
            }
            self.state.append(
                "recovery_run_prepared", prepared,
                unique_fields=("capability_id",),
            )
            self.state.append(
                "capability_consumed",
                {
                    "schema": LOG_SCHEMA,
                    "capability_id": selected.capability_id,
                    "run_id": run_id,
                    "consumed_at": wall,
                },
                unique_fields=("capability_id",),
            )
            self._failpoint("after_prepare")
        terminal = self._terminal_for(prepared["run_id"])
        if terminal is not None:
            return terminal
        if spec["effect"] == "read":
            result = (
                self.doctor(
                    task_lane_state=str(current_pre_state.get("task_lane_state", "unknown")),
                    launcher_status=str(current_pre_state.get("launcher_status", "unknown")),
                    snapshot_status=str(current_pre_state.get("snapshot_status", "unknown")),
                    hook_generation_status=str(
                        current_pre_state.get("hook_generation_status", "unknown")
                    ),
                    skill_catalog_status=str(
                        current_pre_state.get("skill_catalog_status", "unknown")
                    ),
                )
                if selected.action == "doctor"
                else self.status()
            )
            return self._record_terminal(
                prepared, "succeeded", "typed_read_completed", result=result
            )

        starts = [
            row for row in self._payloads("recovery_dispatch_started")
            if row.get("run_id") == prepared["run_id"]
        ]
        if len(starts) >= MAX_DISPATCH_ATTEMPTS:
            return self._record_terminal(
                prepared, "blocked", "bounded_reprobe_exhausted",
                result={"attempts": len(starts)},
            )
        attempt = len(starts) + 1
        mode = "apply" if attempt == 1 else "reprobe"
        wall, mono = self._now()
        execution_request = {
            "schema": EXECUTION_REQUEST_SCHEMA,
            "run_id": prepared["run_id"],
            "effect_id": prepared["effect_id"],
            "capability_id": selected.capability_id,
            "provider": selected.provider,
            "session_id": selected.session_id,
            "workspace": selected.workspace,
            "installed_generation": selected.installed_generation,
            "action": selected.action,
            "target_identity": selected.target_identity,
            "expected_pre_state": _thaw(selected.expected_pre_state),
            "allowed_changes": list(selected.allowed_changes),
            "attempt": attempt,
            "mode": mode,
        }
        start = {
            "schema": LOG_SCHEMA,
            "dispatch_id": _plain_digest("recovery-dispatch", execution_request),
            "run_id": prepared["run_id"],
            "attempt": attempt,
            "mode": mode,
            "request": execution_request,
            "observed_wall": wall,
            "observed_mono": mono,
        }
        self.state.append(
            "recovery_dispatch_started", start,
            unique_fields=("run_id", "attempt"),
        )
        self.record_progress(
            prepared["run_id"], stage=f"dispatch:{attempt}",
            message=f"{selected.action} {mode}",
        )
        self._failpoint("after_dispatch_start")
        try:
            method = (
                getattr(self.trusted_adapter, spec["method"], None)
                if mode == "apply"
                else getattr(self.trusted_adapter, "reprobe", None)
            )
            if not callable(method):
                raise RecoveryLaneError("trusted adapter method is unavailable")
            raw_result = method(deepcopy(execution_request))
            self._failpoint("after_adapter")
            adapter_result = _validate_adapter_result(raw_result)
        except Exception as error:
            adapter_result = {
                "schema": ADAPTER_RESULT_SCHEMA,
                "run_id": prepared["run_id"],
                "effect_id": prepared["effect_id"],
                "adapter_identity": str(self.adapter_identity),
                "action": selected.action,
                "target_identity": selected.target_identity,
                "status": "unknown",
                "observed_post_state": {},
                "detail": {"error": type(error).__name__},
            }
        expected_adapter = {
            "run_id": prepared["run_id"],
            "effect_id": prepared["effect_id"],
            "adapter_identity": self.adapter_identity,
            "action": selected.action,
            "target_identity": selected.target_identity,
        }
        if any(adapter_result[field] != value for field, value in expected_adapter.items()):
            raise RecoveryLaneError("recovery adapter result binding is invalid")
        observation = {
            "schema": LOG_SCHEMA,
            "observation_id": _plain_digest("recovery-dispatch-result", {
                "attempt": attempt, "result": adapter_result,
            }),
            "run_id": prepared["run_id"],
            "attempt": attempt,
            "result": adapter_result,
            "observed_wall": self.wall_clock(),
            "observed_mono": self.monotonic_clock(),
        }
        self.state.append(
            "recovery_dispatch_observed", observation,
            unique_fields=("run_id", "attempt"),
        )
        self._failpoint("after_dispatch_receipt")
        result_identity = _plain_digest("recovery-adapter-result", adapter_result)
        verify_request = {
            "schema": PROTOCOL_SCHEMA,
            "run_id": prepared["run_id"],
            "effect_id": prepared["effect_id"],
            "action": selected.action,
            "target_identity": selected.target_identity,
            "expected_pre_state": _thaw(selected.expected_pre_state),
            "adapter_result": adapter_result,
            "result_identity": result_identity,
        }
        receipt = _validate_verifier_receipt(
            self.trusted_verifier.verify(deepcopy(verify_request))
        )
        expected_receipt = {
            "verifier_identity": self.verifier_identity,
            "run_id": prepared["run_id"],
            "effect_id": prepared["effect_id"],
            "action": selected.action,
            "target_identity": selected.target_identity,
            "result_identity": result_identity,
        }
        if any(receipt[field] != value for field, value in expected_receipt.items()):
            raise RecoveryLaneError("independent verifier binding is invalid")
        self.state.append(
            "recovery_verifier_observed", receipt,
            unique_fields=("receipt_id",),
        )
        self.record_progress(
            prepared["run_id"], stage=f"verify:{attempt}",
            message=receipt["status"],
        )
        if adapter_result["status"] == "completed" and receipt["status"] == "passed":
            return self._record_terminal(
                prepared, "succeeded", "independent_verification_passed",
                result={
                    "adapter": adapter_result,
                    "verifier_receipt_id": receipt["receipt_id"],
                },
            )
        if adapter_result["status"] == "failed" and receipt["status"] == "passed":
            return self._record_terminal(
                prepared, "failed", "verified_adapter_failure",
                result={
                    "adapter": adapter_result,
                    "verifier_receipt_id": receipt["receipt_id"],
                },
            )
        if attempt >= MAX_DISPATCH_ATTEMPTS:
            return self._record_terminal(
                prepared, "blocked", "bounded_reprobe_exhausted",
                result={
                    "adapter_status": adapter_result["status"],
                    "verifier_status": receipt["status"],
                    "attempts": attempt,
                },
            )
        return {
            "schema": RESULT_SCHEMA,
            "run_id": prepared["run_id"],
            "status": "awaiting_verification",
            "attempts": attempt,
            "next_action": "bounded_reprobe",
        }
