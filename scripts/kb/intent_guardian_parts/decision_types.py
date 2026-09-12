"""Immutable decision values and controlled supervision errors."""
from __future__ import annotations

from dataclasses import dataclass
import re


class IntentGuardianError(RuntimeError):
    """A controlled contract or supervision error."""


@dataclass(frozen=True)
class DecisionV2:
    dispatch: str
    would_dispatch: str
    lifecycle: str
    authority: str
    verification: str
    evidence_state: str
    severity: str
    reason: str
    fingerprint: str
    pause_class: str = ""
    reason_code: str = "policy_evaluation"
    decision_stage: str = "policy"
    secondary_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        domains = {
            "dispatch": ({"allow", "deny", "defer"}, self.dispatch),
            "would_dispatch": (
                {"allow", "deny", "defer"}, self.would_dispatch,
            ),
            "lifecycle": ({"continue", "pause"}, self.lifecycle),
            "authority": (
                {"none", "task", "continuation", "human_grant"},
                self.authority,
            ),
            "verification": ({"none", "required"}, self.verification),
            "evidence_state": ({"observed", "gap"}, self.evidence_state),
        }
        for field, (allowed, value) in domains.items():
            if value not in allowed:
                raise ValueError(f"DecisionV2 {field} is invalid: {value!r}")
        if self.lifecycle == "pause" and self.dispatch == "allow":
            raise ValueError("DecisionV2 cannot dispatch while pausing")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", self.reason_code):
            raise ValueError(
                f"DecisionV2 reason_code is invalid: {self.reason_code!r}"
            )
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", self.decision_stage):
            raise ValueError(
                f"DecisionV2 decision_stage is invalid: {self.decision_stage!r}"
            )
        if not isinstance(self.secondary_reasons, tuple) or not all(
            isinstance(value, str) and value for value in self.secondary_reasons
        ):
            raise ValueError("DecisionV2 secondary_reasons must be non-empty strings")

    @property
    def action(self) -> str:
        """Legacy dispatch view: defer remains a non-dispatching deny."""
        return "allow" if self.dispatch == "allow" else "deny"

    @property
    def would_action(self) -> str:
        return "allow" if self.would_dispatch == "allow" else "deny"

    @property
    def pause(self) -> bool:
        return self.lifecycle == "pause"

    @property
    def verification_required(self) -> bool:
        return self.verification == "required"

    @property
    def awaiting_human(self) -> bool:
        return self.dispatch == "defer"

    @property
    def observation_gap(self) -> bool:
        return self.evidence_state == "gap"


# Legacy public type alias.
Decision = DecisionV2
