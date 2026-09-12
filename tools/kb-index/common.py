#!/usr/bin/env python3
"""Shared parsing, chunking, and SQLite helpers for the local KB index."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from corpus_manifest import MANIFEST_RELATIVE, document_sha256, load_manifest
from memory import _configure_utf8_stdio as configure_utf8_stdio

_SEDIMENTATION_RUNTIME = Path(__file__).resolve().parents[2] / "scripts" / "kb"
if str(_SEDIMENTATION_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_SEDIMENTATION_RUNTIME))
from sedimentation_schema import (  # noqa: E402
    role_for_heading as sedimentation_role_for_heading,
    sections as sedimentation_sections,
)


MODEL_NAME = "BAAI/bge-small-zh-v1.5"
SCHEMA_VERSION = "3"
DEFAULT_WEIGHTS = {"bm25": 0.5, "vector": 0.5}
CONTAINER_DIRS = {"anti-patterns", "platform-kb", "tech-docs", "work-model"}
EXCLUDED_BASENAMES = {"INDEX.md", "README.md"}
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")
H1_RE = re.compile(r"^#\s+(.+?)\s*$")
H2_RE = re.compile(r"^##\s+(.+?)\s*$")
NUMBER_PREFIX_RE = re.compile(r"^\d{4}\s*(?:—|-)\s*")


@dataclass(frozen=True)
class Document:
    path: Path
    sha256: str
    doc_id: str
    title: str
    container: str
    platform: str
    related: tuple[str, ...]
    sedimentation_schema: str
    problem_type: str
    evidence_status: str
    body: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    role: str
    container: str
    platform: str
    problem_type: str
    evidence_status: str
    source_path: str
    text: str


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def kb_home() -> Path:
    """Stable runtime state root; hooks mirror this tiny resolver independently."""
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def db_path() -> Path:
    return kb_home() / "kb.db"


def corpus_fingerprint(root: Path) -> str:
    if (root / MANIFEST_RELATIVE).is_file():
        return load_manifest(root).corpus_sha256
    return hashlib.sha256((root / "knowledge" / "INDEX.md").read_bytes()).hexdigest()


def _filter_documents(candidates: list[Path]) -> list[Path]:
    documents = [
        path
        for path in candidates
        if path.suffix.lower() == ".md"
        and path.name not in EXCLUDED_BASENAMES
        and len(path.parts) >= 3
        and path.parts[0] == "knowledge"
        and path.parts[1] in CONTAINER_DIRS
    ]
    return sorted(documents, key=lambda item: item.as_posix())


def git_tracked_documents(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "knowledge"],
        cwd=root,
        stderr=subprocess.PIPE,
    )
    candidates = [Path(raw.decode("utf-8")) for raw in output.split(b"\0") if raw]
    return _filter_documents(candidates)


def tracked_documents(root: Path) -> list[Path]:
    if (root / MANIFEST_RELATIVE).is_file():
        return [Path(document.path) for document in load_manifest(root).documents]
    if (root / ".git").exists():
        return git_tracked_documents(root)
    knowledge_root = root / "knowledge"
    candidates = [
        path.relative_to(root) for path in knowledge_root.rglob("*") if path.is_file()
    ]
    return _filter_documents(candidates)


def decode_scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, str) else str(decoded)
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def decode_inline_list(value: str) -> tuple[str, ...]:
    """Decode the flat inline-list syntax accepted by the frontmatter linter."""
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        raise ValueError("expected an inline list: [doc-id, ...]")
    inner = value[1:-1].strip()
    if not inner:
        return ()
    return tuple(
        item.strip().strip("'\"") for item in inner.split(",") if item.strip()
    )


def parse_document(root: Path, relative: Path) -> Document:
    data = (root / relative).read_bytes()
    text = data.decode("utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{relative}: missing frontmatter")
    try:
        end = next(
            index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"
        )
    except StopIteration as error:
        raise ValueError(f"{relative}: unclosed frontmatter") from error

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        match = KEY_RE.match(line)
        if match:
            fields[match.group(1)] = decode_scalar(match.group(2) or "")
    for key in ("doc_id", "container", "platform"):
        if not fields.get(key):
            raise ValueError(f"{relative}: missing or empty {key}")

    body = "\n".join(lines[end + 1 :]).strip()
    title = ""
    for line in lines[end + 1 :]:
        match = H1_RE.match(line)
        if match:
            title = match.group(1).strip()
            break
    if not title:
        title = relative.stem
    title = NUMBER_PREFIX_RE.sub("", title, count=1).strip()
    return Document(
        path=relative,
        sha256=document_sha256(data),
        doc_id=fields["doc_id"],
        title=title,
        container=fields["container"],
        platform=fields["platform"],
        related=decode_inline_list(fields["related"]) if "related" in fields else (),
        sedimentation_schema=fields.get("sedimentation_schema", ""),
        problem_type=fields.get("problem_type", ""),
        evidence_status=fields.get("evidence_status", ""),
        body=body,
    )


def _split_long(text: str, limit: int = 1500) -> list[str]:
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    current = ""
    paragraphs = re.split(r"\n\s*\n", text)
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        while len(paragraph) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(paragraph[:limit].strip())
            paragraph = paragraph[limit:].strip()
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) > limit:
            pieces.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces or [text]


def chunks_for(document: Document) -> list[Chunk]:
    source_path = document.path.as_posix()
    if document.sedimentation_schema == "2":
        texts: list[tuple[str, str, str]] = []
        for section in sedimentation_sections(
            "---\n"
            f"doc_id: {document.doc_id}\n"
            f"container: {document.container}\n"
            f"platform: {document.platform}\n"
            "---\n"
            f"{document.body}"
        ):
            role = sedimentation_role_for_heading(section.heading)
            # The parent "判定样本" section contains all four child examples. Indexing
            # it as general would erase the explicit skip/apply polarity of its children.
            if role == "general" and section.heading.rstrip("：:").strip() == "判定样本":
                continue
            segment = f"## {section.heading}\n\n{section.content}".strip()
            for piece in _split_long(segment):
                texts.append((section.heading, role, f"# {document.title}\n\n{piece}".strip()))
        if not texts:
            texts = [("", "general", document.body)]
    elif document.container == "anti-patterns":
        texts = [("", "general", document.body)]
    else:
        segments: list[tuple[str, str]] = []
        section = ""
        current: list[str] = []
        for line in document.body.splitlines():
            match = H2_RE.match(line)
            if match:
                if current and "\n".join(current).strip():
                    segments.append((section, "\n".join(current).strip()))
                section = match.group(1).strip()
                current = [line]
            else:
                current.append(line)
        if current and "\n".join(current).strip():
            segments.append((section, "\n".join(current).strip()))
        texts = []
        for section_name, segment in segments:
            for piece in _split_long(segment):
                prefix = f"# {document.title}"
                texts.append((section_name, "general", f"{prefix}\n\n{piece}".strip()))

    chunks: list[Chunk] = []
    for index, (section, role, text) in enumerate(texts):
        chunks.append(
            Chunk(
                chunk_id=f"{document.doc_id}#{index:04d}",
                doc_id=document.doc_id,
                title=document.title,
                section=section,
                role=role,
                container=document.container,
                platform=document.platform,
                problem_type=document.problem_type,
                evidence_status=document.evidence_status,
                source_path=source_path,
                text=text,
            )
        )
    return chunks


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            title TEXT NOT NULL,
            section TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'general',
            container TEXT NOT NULL,
            platform TEXT NOT NULL,
            problem_type TEXT NOT NULL DEFAULT '',
            evidence_status TEXT NOT NULL DEFAULT '',
            source_path TEXT NOT NULL,
            text TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(seg_text);
        CREATE TABLE IF NOT EXISTS vectors (
            chunk_id TEXT PRIMARY KEY REFERENCES chunks(chunk_id) ON DELETE CASCADE,
            dim INTEGER NOT NULL,
            emb BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS manifest (
            path TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS edges (
            src_doc_id TEXT NOT NULL,
            dst_doc_id TEXT NOT NULL,
            rel TEXT NOT NULL,
            PRIMARY KEY (src_doc_id, dst_doc_id, rel)
        );
        CREATE INDEX IF NOT EXISTS chunks_source_path ON chunks(source_path);
        CREATE INDEX IF NOT EXISTS chunks_filters ON chunks(container, platform);
        CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst_doc_id, rel);
        """
    )
    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(chunks)").fetchall()
    }
    if "role" not in columns:
        connection.execute(
            "ALTER TABLE chunks ADD COLUMN role TEXT NOT NULL DEFAULT 'general'"
        )
    if "problem_type" not in columns:
        connection.execute(
            "ALTER TABLE chunks ADD COLUMN problem_type TEXT NOT NULL DEFAULT ''"
        )
    if "evidence_status" not in columns:
        connection.execute(
            "ALTER TABLE chunks ADD COLUMN evidence_status TEXT NOT NULL DEFAULT ''"
        )
    connection.execute("CREATE INDEX IF NOT EXISTS chunks_roles ON chunks(role)")


def git_head(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
