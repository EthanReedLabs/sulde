"""Independent recovery loop for already-decided native transactions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def recover_native_decisions_independently(
    path: Path,
    *,
    pending: Callable[[Path], list[dict[str, Any]]],
    advance: Callable[[Path, dict[str, Any]], dict[str, Any]],
    pending_errors: tuple[type[BaseException], ...],
    advance_errors: tuple[type[BaseException], ...],
    error_factory: Callable[[str], Exception],
) -> list[dict[str, Any]]:
    """Enumerate once and retain one failed row without blocking later rows."""
    try:
        transactions = pending(path.expanduser().resolve())
    except pending_errors as error:
        raise error_factory(
            f"cannot enumerate native decision transactions: {error}"
        ) from error

    recovered: list[dict[str, Any]] = []
    for transaction in transactions:
        try:
            advanced = advance(path, transaction)
            if advanced.get("stage") != transaction.get("stage"):
                recovered.append(advanced)
        except advance_errors as error:
            recovered.append(
                {
                    **transaction,
                    "recovery_status": "failed",
                    "recovery_error": f"{type(error).__name__}: {error}"[:1000],
                }
            )
    return recovered
