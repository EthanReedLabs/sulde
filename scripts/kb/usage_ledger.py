"""Incremental LLM usage accounting for managed runs (C4, R1-05).

Provider event streams are durably captured line-by-line by the managed-run
monitor (fsync per line plus an audit cursor).  This module turns those raw
lines into a per-run usage report with explicit three-state accounting:

- ``complete``    — a recognized *cumulative* fact from the provider: Claude
  ``result.usage``; Codex ``turn.completed.usage`` (the real app-server
  producer) and Codex ``token_count`` totals.
- ``lower_bound`` — only per-turn fragments were observed, or fragments
  followed a cumulative snapshot; the value is a floor, never zero.
- ``unknown``     — no recognized usage fact; the value is null, never zero.

Provider semantics are kept apart: cumulative facts replace the running
total (monotonically — a smaller late cumulative is counted as out-of-order
and ignored, never allowed to overwrite a newer one), per-turn fragments
accumulate on their own.  A cumulative snapshot followed by turn fragments
is reported as a lower bound with ``basis: cumulative-plus-fragments``
(total plus known post-snapshot consumption) — totals and increments are
never silently conflated.  Cached counts map to their own metrics and are
never re-added into input totals (Claude's ``cache_read``/``cache_creation``
and Codex's ``cached_input``/``cache_write`` are distinct fields in both
producers' inputs).

Incremental scanning persists cursor + report + stream identity atomically
(``{slug}.usage-cursor.json``): each scan re-hashes the consumed prefix
(streaming, bounded memory) to detect truncation and rewrite honestly, then
parses only the appended tail — the integrity check is O(stream) hashing per
scan, not a claim of tail-only reads.  A replaced stream (new inode) starts
a new stream generation; prior-stream totals are preserved in the report
under ``prior_streams``.  No new data keeps the previous report unchanged.

Reports bind to one run (run_id) so aggregates dedup by run identity.  Only
completion-metric fields are collected — token counts and stream shapes; no
prompts, tool outputs, or reasoning content.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


USAGE_REPORT_SCHEMA = "sulde-usage-report-v1"
USAGE_CURSOR_SCHEMA = "sulde-usage-cursor-v1"
USAGE_METRIC_STATES = frozenset({"complete", "lower_bound", "unknown"})
USAGE_METRICS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
)
_USAGE_INT_KEYS = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cached_input_tokens": "cached_input_tokens",
    "cache_read_input_tokens": "cached_input_tokens",
    "cache_creation_input_tokens": "cache_write_input_tokens",
    "cache_write_input_tokens": "cache_write_input_tokens",
}


class UsageLedgerError(RuntimeError):
    """A usage stream cannot be scanned safely."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write cursor/report state atomically: tmp file, fsync, rename, fsync dir."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _hash_prefix(path: Path, length: int) -> str:
    """Streaming hash of the first ``length`` bytes (bounded memory)."""
    digest = hashlib.sha256()
    remaining = length
    with path.open("rb") as handle:
        while remaining > 0:
            chunk = handle.read(min(1 << 20, remaining))
            if not chunk:
                raise UsageLedgerError(
                    "usage stream shrank while hashing its prefix"
                )
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def _empty_metrics() -> dict[str, dict[str, Any]]:
    return {
        metric: {"value": None, "state": "unknown"}
        for metric in USAGE_METRICS
    }


def _usage_from_mapping(mapping: dict[str, Any]) -> dict[str, int] | None:
    totals: dict[str, int] = {}
    for key, value in mapping.items():
        metric = _USAGE_INT_KEYS.get(key)
        if metric is None or isinstance(value, bool) or not isinstance(value, int):
            continue
        totals[metric] = totals.get(metric, 0) + value
    return totals or None


def _recognized_usage(record: dict[str, Any], provider: str) -> str | None:
    """Classify one provider line as cumulative or per-turn usage evidence."""
    record_type = str(record.get("type") or "")
    if provider == "claude":
        if record_type == "result" and isinstance(record.get("usage"), dict):
            return "cumulative"
        if record_type == "assistant":
            message = record.get("message")
            if isinstance(message, dict) and isinstance(message.get("usage"), dict):
                return "turn"
        return None
    if provider == "codex":
        # Real app-server protocol: the turn summary carries thread-cumulative
        # usage for the turn block it closes.
        if record_type == "turn.completed" and isinstance(record.get("usage"), dict):
            return "cumulative"
        if record_type == "token_count":
            info = record.get("info")
            if isinstance(info, dict):
                if isinstance(info.get("total_token_usage"), dict):
                    return "cumulative"
                if isinstance(info.get("usage"), dict):
                    return "cumulative"
                if isinstance(info.get("last_token_usage"), dict):
                    return "turn"
        payload = record.get("payload")
        if (
            record_type == "event_msg"
            and isinstance(payload, dict)
            and str(payload.get("type") or "") == "token_count"
        ):
            if isinstance(payload.get("total_token_usage"), dict):
                return "cumulative"
            if isinstance(payload.get("usage"), dict):
                return "cumulative"
            if isinstance(payload.get("last_token_usage"), dict):
                return "turn"
    return None


def _usage_values(record: dict[str, Any], provider: str) -> dict[str, int] | None:
    record_type = str(record.get("type") or "")
    if provider == "claude":
        if record_type == "result":
            return _usage_from_mapping(record.get("usage") or {})
        if record_type == "assistant":
            message = record.get("message")
            if isinstance(message, dict):
                return _usage_from_mapping(message.get("usage") or {})
        return None
    if provider == "codex":
        if record_type == "turn.completed":
            return _usage_from_mapping(record.get("usage") or {})
        info = record.get("info")
        if record_type == "token_count" and isinstance(info, dict):
            for container in ("total_token_usage", "usage", "last_token_usage"):
                if isinstance(info.get(container), dict):
                    return _usage_from_mapping(info[container])
        payload = record.get("payload")
        if (
            record_type == "event_msg"
            and isinstance(payload, dict)
            and str(payload.get("type") or "") == "token_count"
        ):
            for container in ("total_token_usage", "usage", "last_token_usage"):
                if isinstance(payload.get(container), dict):
                    return _usage_from_mapping(payload[container])
    return None


class _RunAccumulator:
    """One run's totals under explicit cumulative/fragment semantics."""

    def __init__(
        self,
        basis: dict[str, Any] | None = None,
        basis_kind: str = "none",
    ) -> None:
        self.metrics = _empty_metrics()
        self.turns_observed = 0
        self.out_of_order_ignored = 0
        self.duplicate_ignored = 0
        self.basis_kind = basis_kind
        if basis:
            self.metrics = json.loads(json.dumps(basis))
            for metric in USAGE_METRICS:
                if metric not in self.metrics:
                    self.metrics[metric] = {"value": None, "state": "unknown"}

    def _last_cumulative(self) -> dict[str, int] | None:
        # Both cumulative bases are monotone floors: a next cumulative fact
        # must be componentwise >= the current total, else it is stale.
        if self.basis_kind not in {"cumulative", "cumulative-plus-fragments"}:
            return None
        return {
            metric: (block["value"] or 0)
            for metric, block in self.metrics.items()
        }

    def apply(self, values: dict[str, int], kind: str) -> None:
        if kind == "cumulative":
            last = self._last_cumulative()
            if last is not None:
                if values == last:
                    self.duplicate_ignored += 1
                    return
                if any(
                    values.get(metric, 0) < (last.get(metric) or 0)
                    for metric in values
                ):
                    # A smaller late cumulative is an out-of-order old report;
                    # it must never overwrite a newer one.
                    self.out_of_order_ignored += 1
                    return
            for metric in USAGE_METRICS:
                if values.get(metric) is not None:
                    self.metrics[metric] = {
                        "value": values[metric],
                        "state": "complete",
                    }
            self.basis_kind = "cumulative"
            return
        # Per-turn fragment.
        self.turns_observed += 1
        if self.basis_kind == "cumulative":
            # Known consumption beyond the cumulative snapshot: keep the
            # cumulative and add the fragment, but honesty drops to a floor.
            for metric in USAGE_METRICS:
                if values.get(metric) is None:
                    continue
                block = self.metrics[metric]
                block["value"] = (block["value"] or 0) + values[metric]
                if block["state"] == "complete":
                    block["state"] = "lower_bound"
            self.basis_kind = "cumulative-plus-fragments"
            return
        for metric in USAGE_METRICS:
            if values.get(metric) is None:
                continue
            block = self.metrics[metric]
            block["value"] = (block["value"] or 0) + values[metric]
            if block["state"] == "unknown":
                block["state"] = "lower_bound"
        if self.basis_kind == "none":
            self.basis_kind = "fragments"

    def report_state(self) -> str:
        if self.basis_kind in {"cumulative", "cumulative-plus-fragments"}:
            if any(
                block["state"] == "lower_bound" for block in self.metrics.values()
            ):
                return "lower_bound"
            return "complete"
        if self.basis_kind == "fragments":
            return "lower_bound"
        return "unknown"

    def basis(self) -> str:
        return self.basis_kind


def _load_cursor(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise UsageLedgerError(f"usage cursor cannot be read: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema") != USAGE_CURSOR_SCHEMA:
        raise UsageLedgerError("usage cursor schema is unrecognized")
    return payload


def scan_usage_incremental(
    events_path: Path,
    cursor_path: Path,
    *,
    provider: str,
    run_id: str,
    slug: str,
    intent_id: str | None = None,
    session_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scan the stream incrementally with persisted, atomic cursor state.

    The cursor binds offset, prefix digest, and stream identity (inode); the
    consumed prefix is re-hashed (streaming) on every scan so truncation and
    same-length rewrites of the consumed region fail closed.  A replaced
    stream (new inode) becomes a new stream generation: prior-stream totals
    move to ``prior_streams`` and accumulation restarts.  With no new
    complete lines the previous report is returned unchanged.
    """
    previous_cursor = _load_cursor(cursor_path)
    prior_streams: list[dict[str, Any]] = []
    previous_report: dict[str, Any] | None = None
    offset = 0
    prefix_digest: str | None = None
    stream_inode: int | None = None
    stream_generation = 1
    if previous_cursor is not None:
        if previous_cursor.get("run_id") not in (None, run_id):
            raise UsageLedgerError(
                "usage cursor belongs to a different run; refusing to mix"
            )
        offset = int(previous_cursor.get("offset") or 0)
        prefix_digest = previous_cursor.get("prefix_sha256")
        stream_inode = previous_cursor.get("stream_inode")
        stream_generation = int(previous_cursor.get("stream_generation") or 1)
        previous_report = previous_cursor.get("report")
        prior_streams = list(previous_cursor.get("prior_streams") or [])
    try:
        metadata = events_path.stat()
    except FileNotFoundError:
        # Nothing observed yet: no fabricated totals, cursor unchanged.
        if previous_report is not None:
            return previous_report, previous_cursor or {}
        empty_report = _base_report(
            provider=provider,
            run_id=run_id,
            slug=slug,
            intent_id=intent_id,
            session_id=session_id,
            metrics=_empty_metrics(),
            state="unknown",
            basis="none",
            turns_observed=0,
            stream_generation=stream_generation,
            prior_streams=prior_streams,
            out_of_order_ignored=0,
            duplicate_ignored=0,
            records_scanned=0,
        )
        return empty_report, {"schema": USAGE_CURSOR_SCHEMA, "run_id": run_id, "offset": 0, "prefix_sha256": None, "stream_inode": None, "stream_generation": stream_generation, "report": empty_report, "prior_streams": prior_streams}
    except OSError as error:
        raise UsageLedgerError(f"usage stream cannot be inspected: {error}") from error
    if stream_inode is not None and metadata.st_ino != stream_inode:
        # Rotation/replacement: preserve prior totals, start a new stream.
        if previous_report is not None:
            prior_streams.append(
                {
                    "stream_generation": stream_generation,
                    "state": previous_report.get("state", "unknown"),
                    "metrics": previous_report.get("metrics"),
                }
            )
        offset = 0
        prefix_digest = None
        stream_generation += 1
        previous_report = None
    if offset > metadata.st_size:
        raise UsageLedgerError(
            "usage stream was truncated below the last consumed offset"
        )
    if offset and prefix_digest is not None:
        actual_prefix = _hash_prefix(events_path, offset)
        if actual_prefix != prefix_digest:
            raise UsageLedgerError(
                "usage stream prefix changed between scans; the file was "
                "rewritten or corrupted"
            )
    with events_path.open("rb") as handle:
        handle.seek(offset)
        tail = handle.read()
    new_offset = offset
    new_lines: list[dict[str, Any]] = []
    if tail:
        if not tail.endswith(b"\n"):
            last_newline = tail.rfind(b"\n")
            if last_newline < 0:
                tail = b""
            else:
                tail = tail[: last_newline + 1]
        if tail:
            for raw in tail.splitlines():
                if not raw.strip():
                    continue
                try:
                    record = json.loads(raw.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    continue
                if isinstance(record, dict):
                    new_lines.append(record)
            new_offset = offset + len(tail)
    if new_offset == offset and previous_report is not None:
        # No new complete data: keep the previous values verbatim.
        return previous_report, previous_cursor or {}
    accumulator = _RunAccumulator(
        basis=(
            previous_report.get("metrics")
            if previous_report is not None
            else None
        ),
        basis_kind=(
            str(previous_report.get("basis") or "none")
            if previous_report is not None
            else "none"
        ),
    )
    if previous_report is not None:
        accumulator.turns_observed = int(previous_report.get("turns_observed") or 0)
        accumulator.out_of_order_ignored = int(
            previous_report.get("out_of_order_ignored") or 0
        )
        accumulator.duplicate_ignored = int(
            previous_report.get("duplicate_ignored") or 0
        )
    for record in new_lines:
        kind = _recognized_usage(record, provider)
        if kind is None:
            continue
        values = _usage_values(record, provider)
        if values is None:
            continue
        accumulator.apply(values, kind)
    new_prefix = _hash_prefix(events_path, new_offset)
    report = _base_report(
        provider=provider,
        run_id=run_id,
        slug=slug,
        intent_id=intent_id,
        session_id=session_id,
        metrics=accumulator.metrics,
        state=accumulator.report_state(),
        basis=accumulator.basis(),
        turns_observed=accumulator.turns_observed,
        stream_generation=stream_generation,
        prior_streams=prior_streams,
        out_of_order_ignored=accumulator.out_of_order_ignored,
        duplicate_ignored=accumulator.duplicate_ignored,
        records_scanned=len(new_lines),
    )
    if previous_report is not None and not new_lines:
        report = previous_report
    cursor = {
        "schema": USAGE_CURSOR_SCHEMA,
        "run_id": run_id,
        "offset": new_offset,
        "prefix_sha256": new_prefix,
        "stream_inode": metadata.st_ino,
        "stream_generation": stream_generation,
        "report": report,
        "prior_streams": prior_streams,
    }
    _atomic_write_json(cursor_path, cursor)
    return report, cursor


def _base_report(
    *,
    provider: str,
    run_id: str,
    slug: str,
    intent_id: str | None,
    session_id: str | None,
    metrics: dict[str, dict[str, Any]],
    state: str,
    basis: str,
    turns_observed: int,
    stream_generation: int,
    prior_streams: list[dict[str, Any]],
    out_of_order_ignored: int,
    duplicate_ignored: int,
    records_scanned: int,
) -> dict[str, Any]:
    return {
        "schema": USAGE_REPORT_SCHEMA,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "slug": slug,
        "provider": provider,
        "intent_id": intent_id,
        "session_id": session_id,
        "state": state,
        "basis": basis,
        "metrics": metrics,
        "turns_observed": turns_observed,
        "stream_generation": stream_generation,
        "prior_streams": prior_streams,
        "out_of_order_ignored": out_of_order_ignored,
        "duplicate_ignored": duplicate_ignored,
        "records_scanned": records_scanned,
    }


def scan_usage(
    events_path: Path,
    *,
    provider: str,
    run_id: str,
    slug: str,
    intent_id: str | None = None,
    session_id: str | None = None,
    start_offset: int = 0,
    prefix_digest: str | None = None,
    prior_metrics: dict[str, dict[str, Any]] | None = None,
    prior_basis: str = "none",
) -> dict[str, Any]:
    """Stateless single-pass scan (low-level; the wired path is incremental).

    When ``prior_metrics``/``prior_basis`` are supplied the scan merges into
    them instead of starting from zero, so repeated scans of one stream
    accumulate rather than reset.
    """
    (
        records,
        _new_offset,
        _new_prefix,
    ) = _read_new_lines(
        events_path,
        start_offset=start_offset,
        prefix_digest=prefix_digest,
    )
    accumulator = _RunAccumulator(basis=prior_metrics, basis_kind=prior_basis)
    for record in records:
        kind = _recognized_usage(record, provider)
        if kind is None:
            continue
        values = _usage_values(record, provider)
        if values is None:
            continue
        accumulator.apply(values, kind)
    return _base_report(
        provider=provider,
        run_id=run_id,
        slug=slug,
        intent_id=intent_id,
        session_id=session_id,
        metrics=accumulator.metrics,
        state=accumulator.report_state(),
        basis=accumulator.basis(),
        turns_observed=accumulator.turns_observed,
        stream_generation=1,
        prior_streams=[],
        out_of_order_ignored=accumulator.out_of_order_ignored,
        duplicate_ignored=accumulator.duplicate_ignored,
        records_scanned=len(records),
    )


def _read_new_lines(
    events_path: Path,
    *,
    start_offset: int,
    prefix_digest: str | None,
) -> tuple[list[dict[str, Any]], int, str]:
    """Read complete JSON lines appended after ``start_offset``.

    Fails closed when the previously seen prefix changed underneath the
    scanner (truncation or rewrite): the caller must report the stream as
    compromised instead of projecting numbers from a rewritten source.
    """
    try:
        payload = events_path.read_bytes()
    except FileNotFoundError:
        return [], 0, ""
    except OSError as error:
        raise UsageLedgerError(f"usage stream cannot be read: {error}") from error
    if len(payload) < start_offset or (
        prefix_digest is not None
        and (hashlib.sha256(payload[:start_offset]).hexdigest() != prefix_digest)
    ):
        raise UsageLedgerError(
            "usage stream prefix changed between scans; the file was "
            "truncated or rewritten"
        )
    chunk = payload[start_offset:]
    if not chunk:
        return [], start_offset, prefix_digest or hashlib.sha256(payload).hexdigest()
    if not chunk.endswith(b"\n"):
        last_newline = chunk.rfind(b"\n")
        if last_newline < 0:
            return [], start_offset, hashlib.sha256(payload[:start_offset]).hexdigest()
        chunk = chunk[: last_newline + 1]
    lines: list[dict[str, Any]] = []
    for raw in chunk.splitlines():
        if not raw.strip():
            continue
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            lines.append(record)
    new_offset = start_offset + len(chunk)
    return lines, new_offset, hashlib.sha256(payload[:new_offset]).hexdigest()


def merge_report_state(*states: str) -> str:
    """Aggregate per-metric states without ever fabricating completeness.

    ``complete`` only when every contributor is complete; any ``lower_bound``
    contributor, or a mix of complete and unknown contributors (partial
    knowledge), yields ``lower_bound``.
    """
    normalized = [state for state in states if state in USAGE_METRIC_STATES]
    if not normalized:
        return "unknown"
    if all(state == "unknown" for state in normalized):
        return "unknown"
    if any(state == "lower_bound" for state in normalized):
        return "lower_bound"
    if all(state == "complete" for state in normalized):
        return "complete"
    return "lower_bound"


def aggregate_usage(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-run usage reports, deduplicating by run identity.

    The same run scanned or reported twice is counted exactly once; two
    independent runs stay separate additions.  A metric is ``complete`` only
    when every contributing run reported it complete; any ``lower_bound``
    or unknown contributor makes the aggregate a floor.
    """
    by_run: dict[str, dict[str, Any]] = {}
    for report in reports:
        if report.get("schema") != USAGE_REPORT_SCHEMA:
            raise UsageLedgerError("aggregate received an unsupported report")
        run_id = str(report.get("run_id") or "")
        if not run_id:
            raise UsageLedgerError("aggregate received a report without run id")
        by_run[run_id] = report
    totals = _empty_metrics()
    for metric in USAGE_METRICS:
        contributors = [
            report["metrics"][metric]
            for report in by_run.values()
            if metric in report.get("metrics", {})
        ]
        if len(contributors) != len(by_run):
            # A run without this metric is unknown for it: floor, not complete.
            states = [
                str(contributor.get("state") or "unknown")
                for contributor in contributors
            ] + ["unknown"] * (len(by_run) - len(contributors))
        else:
            states = [
                str(contributor.get("state") or "unknown")
                for contributor in contributors
            ]
        values = [
            contributor.get("value")
            for contributor in contributors
            if contributor.get("value") is not None
        ]
        if not values:
            continue  # stays unknown / null
        totals[metric]["value"] = sum(values)
        if all(state == "complete" for state in states):
            totals[metric]["state"] = "complete"
        else:
            totals[metric]["state"] = "lower_bound"
    overall = merge_report_state(
        *(report.get("state", "unknown") for report in by_run.values())
    )
    return {
        "schema": "sulde-usage-aggregate-v1",
        "aggregate_at": datetime.now(timezone.utc).isoformat(),
        "run_count": len(by_run),
        "state": overall,
        "metrics": totals,
    }


def write_usage_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
