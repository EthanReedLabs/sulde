"""Read-only legacy projection and cutover comparison."""

from .cutover import CutoverAssessment, assess_cutover
from .legacy_adapter import adapt_legacy_projection, collect_legacy_cut
from .models import (
    LegacyControlCut,
    LegacyCutChanged,
    LegacyProjectionError,
    LegacySemanticProjection,
    SourceFingerprint,
)

__all__ = [
    "CutoverAssessment",
    "LegacyControlCut",
    "LegacyCutChanged",
    "LegacyProjectionError",
    "LegacySemanticProjection",
    "SourceFingerprint",
    "adapt_legacy_projection",
    "assess_cutover",
    "collect_legacy_cut",
]
