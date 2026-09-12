from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence

MANIFEST_RELATIVE = Path("knowledge/MANIFEST.json")
MANIFEST_SCHEMA_VERSION = 1
WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class ManifestDocument:
    path: str
    sha256: str


@dataclass(frozen=True)
class CorpusManifest:
    schema_version: int
    documents: tuple[ManifestDocument, ...]
    document_count: int
    corpus_sha256: str


def canonical_document_bytes(data: bytes) -> bytes:
    text = data.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def document_sha256(data: bytes) -> str:
    return hashlib.sha256(canonical_document_bytes(data)).hexdigest()


def normalize_manifest_path(raw: str) -> str:
    if "\\" in raw:
        raise ManifestError(f"manifest path must use POSIX separators: {raw}")
    normalized = unicodedata.normalize("NFC", raw)
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestError(f"unsafe manifest path: {raw}")
    for part in path.parts:
        if part.rstrip(" .") != part:
            raise ManifestError(f"non-portable manifest path: {raw}")
        if part.split(".", 1)[0].casefold() in WINDOWS_RESERVED:
            raise ManifestError(f"Windows-reserved manifest path: {raw}")
    return path.as_posix()


def _corpus_sha256(documents: Sequence[ManifestDocument]) -> str:
    digest = hashlib.sha256()
    for document in documents:
        digest.update(document.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(document.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_documents(documents: Sequence[ManifestDocument]) -> tuple[ManifestDocument, ...]:
    ordered = tuple(sorted(documents, key=lambda item: item.path))
    if tuple(documents) != ordered:
        raise ManifestError("manifest documents must be sorted by path")
    portable: dict[str, str] = {}
    for document in ordered:
        normalized = normalize_manifest_path(document.path)
        if normalized != document.path:
            raise ManifestError(f"manifest path is not NFC-normalized: {document.path}")
        key = normalized.casefold()
        if key in portable:
            raise ManifestError(f"manifest path collision: {portable[key]} and {normalized}")
        if not _is_digest(document.sha256):
            raise ManifestError(f"invalid document sha256: {normalized}")
        portable[key] = normalized
    return ordered


def build_manifest(root: Path, paths: Sequence[Path]) -> CorpusManifest:
    documents = tuple(sorted(
        (
            ManifestDocument(
                path=normalize_manifest_path(path.as_posix()),
                sha256=document_sha256((root / path).read_bytes()),
            )
            for path in paths
        ),
        key=lambda item: item.path,
    ))
    documents = _validate_documents(documents)
    return CorpusManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        documents=documents,
        document_count=len(documents),
        corpus_sha256=_corpus_sha256(documents),
    )


def render_manifest(manifest: CorpusManifest) -> str:
    payload = {
        "schema_version": manifest.schema_version,
        "documents": [
            {"path": document.path, "sha256": document.sha256}
            for document in manifest.documents
        ],
        "document_count": manifest.document_count,
        "corpus_sha256": manifest.corpus_sha256,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def write_manifest(root: Path, manifest: CorpusManifest) -> None:
    output = root / MANIFEST_RELATIVE
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name("MANIFEST.json.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_manifest(manifest))
    os.replace(temporary, output)


def load_manifest(root: Path, verify_files: bool = True) -> CorpusManifest:
    path = root / MANIFEST_RELATIVE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read corpus manifest: {path}: {error}") from error
    required = {"schema_version", "documents", "document_count", "corpus_sha256"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise ManifestError("manifest root must contain exactly the schema fields")
    if payload["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(f"unsupported manifest schema: {payload['schema_version']}")
    raw_documents = payload["documents"]
    if not isinstance(raw_documents, list):
        raise ManifestError("manifest documents must be a list")
    documents: list[ManifestDocument] = []
    for raw in raw_documents:
        if not isinstance(raw, dict) or set(raw) != {"path", "sha256"}:
            raise ManifestError("manifest document must contain path and sha256")
        if not isinstance(raw["path"], str) or not isinstance(raw["sha256"], str):
            raise ManifestError("manifest path and sha256 must be strings")
        documents.append(ManifestDocument(raw["path"], raw["sha256"]))
    ordered = _validate_documents(documents)
    if payload["document_count"] != len(ordered):
        raise ManifestError("manifest document_count mismatch")
    computed = _corpus_sha256(ordered)
    if not _is_digest(payload["corpus_sha256"]) or payload["corpus_sha256"] != computed:
        raise ManifestError("manifest corpus_sha256 mismatch")
    root_resolved = root.resolve()
    if verify_files:
        for document in ordered:
            target = root / Path(document.path)
            try:
                resolved = target.resolve(strict=True)
            except OSError as error:
                raise ManifestError(f"manifest document missing: {document.path}") from error
            if not resolved.is_relative_to(root_resolved) or not target.is_file():
                raise ManifestError(f"manifest path escapes root: {document.path}")
            if document_sha256(target.read_bytes()) != document.sha256:
                raise ManifestError(f"sha256 mismatch: {document.path}")
    return CorpusManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        documents=ordered,
        document_count=len(ordered),
        corpus_sha256=computed,
    )
