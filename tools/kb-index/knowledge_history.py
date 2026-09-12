from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from corpus_manifest import (
    CorpusManifest,
    ManifestError,
    load_manifest,
    normalize_manifest_path,
)


HISTORY_RELATIVE = Path("knowledge/HISTORY.json")
HISTORY_SCHEMA = "sulde-knowledge-history-v1"
HISTORY_SCHEMA_VERSION = 1


class HistoryError(ValueError):
    pass


@dataclass(frozen=True)
class HistoryDocument:
    path: str
    sha256: str
    last_commit_at: str


@dataclass(frozen=True)
class KnowledgeHistory:
    schema: str
    schema_version: int
    documents: tuple[HistoryDocument, ...]
    document_count: int
    corpus_sha256: str
    history_sha256: str


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise HistoryError(f"history payload is not canonical JSON: {error}") from error
    return rendered.encode("utf-8", "strict")


def canonical_history_sha256(payload: Mapping[str, object]) -> str:
    """Digest a history payload excluding its self-digest field."""
    unsigned = dict(payload)
    unsigned.pop("history_sha256", None)
    return hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest()


def _parse_timestamp(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise HistoryError(f"history timestamp must be a string: {path}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise HistoryError(f"invalid history timestamp for {path}: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HistoryError(f"history timestamp lacks timezone for {path}: {value}")
    if parsed.microsecond or parsed.isoformat(timespec="seconds") != value:
        raise HistoryError(
            f"history timestamp is not canonical ISO seconds: {path}: {value}"
        )
    return value


def _history_payload(
    documents: Sequence[HistoryDocument],
    corpus_sha256: str,
) -> dict[str, object]:
    return {
        "schema": HISTORY_SCHEMA,
        "schema_version": HISTORY_SCHEMA_VERSION,
        "documents": [
            {
                "path": document.path,
                "sha256": document.sha256,
                "last_commit_at": document.last_commit_at,
            }
            for document in documents
        ],
        "document_count": len(documents),
        "corpus_sha256": corpus_sha256,
    }


def _git_last_commits(
    repository: Path,
    paths: Sequence[str],
) -> dict[str, str]:
    marker = b"HISTORY-TIMESTAMP:"
    expected = {path.encode("utf-8", "strict"): path for path in paths}
    try:
        completed = subprocess.run(
            [
                "git",
                "-c",
                "core.quotePath=false",
                "log",
                "--format=HISTORY-TIMESTAMP:%cI",
                "--name-only",
                "-z",
                "--no-renames",
                "--",
                *paths,
            ],
            cwd=repository,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", b"")
        if isinstance(detail, bytes):
            rendered = detail.decode("utf-8", errors="replace").strip()
        else:
            rendered = str(detail).strip()
        raise HistoryError(f"cannot read Git corpus history: {rendered}") from error

    current_timestamp: str | None = None
    found: dict[str, str] = {}
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        path = expected.get(raw)
        if path is None and raw.startswith(b"\n"):
            path = expected.get(raw[1:])
        if path is not None:
            if path in found:
                continue
            if current_timestamp is None:
                raise HistoryError(f"Git history omitted commit metadata for {path}")
            found[path] = current_timestamp
            continue
        token = raw[1:] if raw.startswith(b"\n") else raw
        if token.startswith(marker):
            try:
                timestamp = token[len(marker) :].decode("ascii", "strict")
            except UnicodeError as error:
                raise HistoryError("Git emitted a non-ASCII commit timestamp") from error
            if timestamp.endswith("Z"):
                timestamp = timestamp[:-1] + "+00:00"
            current_timestamp = _parse_timestamp(timestamp, "<git commit>")

    missing = [path for path in paths if path not in found]
    if missing:
        raise HistoryError(
            "no Git history for corpus document(s): " + ", ".join(missing)
        )
    return found


def build_history(
    root: Path,
    repository: Path,
    *,
    manifest: CorpusManifest | None = None,
) -> KnowledgeHistory:
    """Build immutable history for root from repository Git metadata."""
    repository = repository.resolve()
    if not (repository / ".git").exists():
        raise HistoryError(f"source repository has no local Git metadata: {repository}")
    if manifest is None:
        try:
            manifest = load_manifest(root, verify_files=True)
        except ManifestError as error:
            raise HistoryError(
                f"cannot build history from corpus manifest: {error}"
            ) from error
    timestamps = _git_last_commits(
        repository,
        [document.path for document in manifest.documents],
    )
    documents = tuple(
        HistoryDocument(
            path=document.path,
            sha256=document.sha256,
            last_commit_at=timestamps[document.path],
        )
        for document in manifest.documents
    )
    payload = _history_payload(documents, manifest.corpus_sha256)
    return KnowledgeHistory(
        schema=HISTORY_SCHEMA,
        schema_version=HISTORY_SCHEMA_VERSION,
        documents=documents,
        document_count=len(documents),
        corpus_sha256=manifest.corpus_sha256,
        history_sha256=canonical_history_sha256(payload),
    )


def render_history(history: KnowledgeHistory) -> str:
    payload = _history_payload(history.documents, history.corpus_sha256)
    if (
        history.schema != HISTORY_SCHEMA
        or type(history.schema_version) is not int
        or history.schema_version != HISTORY_SCHEMA_VERSION
        or type(history.document_count) is not int
        or history.document_count != len(history.documents)
        or not _is_digest(history.corpus_sha256)
        or history.history_sha256 != canonical_history_sha256(payload)
    ):
        raise HistoryError("cannot render inconsistent knowledge history")
    payload["history_sha256"] = history.history_sha256
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def write_history(root: Path, history: KnowledgeHistory) -> None:
    target = root / HISTORY_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name("HISTORY.json.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_history(history))
    os.replace(temporary, target)


def load_history(
    root: Path,
    *,
    manifest: CorpusManifest | None = None,
) -> KnowledgeHistory:
    if manifest is None:
        try:
            manifest = load_manifest(root, verify_files=True)
        except ManifestError as error:
            raise HistoryError(f"cannot verify history corpus: {error}") from error
    path = root / HISTORY_RELATIVE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HistoryError(f"cannot read knowledge history: {path}: {error}") from error
    required = {
        "schema",
        "schema_version",
        "documents",
        "document_count",
        "corpus_sha256",
        "history_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise HistoryError("history root must contain exactly the schema fields")
    if not isinstance(payload["schema"], str) or payload["schema"] != HISTORY_SCHEMA:
        raise HistoryError(f"unsupported history schema: {payload['schema']!r}")
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != HISTORY_SCHEMA_VERSION
    ):
        raise HistoryError(
            f"unsupported history schema version: {payload['schema_version']!r}"
        )
    raw_documents = payload["documents"]
    if not isinstance(raw_documents, list):
        raise HistoryError("history documents must be a list")
    documents: list[HistoryDocument] = []
    portable: dict[str, str] = {}
    for raw in raw_documents:
        if (
            not isinstance(raw, dict)
            or set(raw) != {"path", "sha256", "last_commit_at"}
        ):
            raise HistoryError(
                "history document must contain exactly path, sha256 and last_commit_at"
            )
        if not isinstance(raw["path"], str) or not isinstance(raw["sha256"], str):
            raise HistoryError("history document path and sha256 must be strings")
        try:
            normalized = normalize_manifest_path(raw["path"])
        except ManifestError as error:
            raise HistoryError(f"unsafe history path: {raw['path']!r}") from error
        if normalized != raw["path"]:
            raise HistoryError(f"history path is not NFC-normalized: {raw['path']}")
        key = normalized.casefold()
        if key in portable:
            raise HistoryError(f"duplicate or colliding history path: {normalized}")
        if not _is_digest(raw["sha256"]):
            raise HistoryError(f"invalid history document sha256: {normalized}")
        portable[key] = normalized
        documents.append(
            HistoryDocument(
                path=normalized,
                sha256=raw["sha256"],
                last_commit_at=_parse_timestamp(raw["last_commit_at"], normalized),
            )
        )
    ordered = tuple(sorted(documents, key=lambda item: item.path))
    if tuple(documents) != ordered:
        raise HistoryError("history documents must be sorted by path")
    if (
        type(payload["document_count"]) is not int
        or payload["document_count"] != len(ordered)
    ):
        raise HistoryError("history document_count mismatch")
    if not _is_digest(payload["corpus_sha256"]):
        raise HistoryError("invalid history corpus_sha256")
    if payload["corpus_sha256"] != manifest.corpus_sha256:
        raise HistoryError("history corpus_sha256 does not match corpus manifest")
    expected_documents = tuple(
        (document.path, document.sha256) for document in manifest.documents
    )
    actual_documents = tuple(
        (document.path, document.sha256) for document in ordered
    )
    if actual_documents != expected_documents:
        raise HistoryError(
            "history document paths or hashes do not match corpus manifest"
        )
    expected_digest = canonical_history_sha256(payload)
    if (
        not _is_digest(payload["history_sha256"])
        or payload["history_sha256"] != expected_digest
    ):
        raise HistoryError("history self digest mismatch")
    return KnowledgeHistory(
        schema=HISTORY_SCHEMA,
        schema_version=HISTORY_SCHEMA_VERSION,
        documents=ordered,
        document_count=len(ordered),
        corpus_sha256=manifest.corpus_sha256,
        history_sha256=expected_digest,
    )
