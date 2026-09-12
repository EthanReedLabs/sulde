#!/usr/bin/env python3
"""Build or incrementally refresh the local T1.5 knowledge index."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time

import jieba
import numpy as np
from fastembed import TextEmbedding

from common import (
    DEFAULT_WEIGHTS,
    MODEL_NAME,
    SCHEMA_VERSION,
    Chunk,
    Document,
    chunks_for,
    configure_utf8_stdio,
    connect,
    corpus_fingerprint,
    create_schema,
    db_path,
    git_head,
    parse_document,
    repo_root,
    tracked_documents,
)


def segmented(text: str) -> str:
    return " ".join(token.strip() for token in jieba.cut_for_search(text) if token.strip())


def delete_path(connection: sqlite3.Connection, source_path: str) -> None:
    rows = connection.execute(
        "SELECT rowid, chunk_id FROM chunks WHERE source_path = ?", (source_path,)
    ).fetchall()
    for row in rows:
        connection.execute("DELETE FROM chunks_fts WHERE rowid = ?", (row["rowid"],))
        connection.execute("DELETE FROM vectors WHERE chunk_id = ?", (row["chunk_id"],))
    connection.execute("DELETE FROM chunks WHERE source_path = ?", (source_path,))


def insert_chunks(
    connection: sqlite3.Connection, chunks: list[Chunk], embeddings: list[np.ndarray]
) -> None:
    for chunk, embedding in zip(chunks, embeddings):
        cursor = connection.execute(
            """
            INSERT INTO chunks(
                chunk_id, doc_id, title, section, role, container, platform,
                problem_type, evidence_status, source_path, text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.chunk_id,
                chunk.doc_id,
                chunk.title,
                chunk.section,
                chunk.role,
                chunk.container,
                chunk.platform,
                chunk.problem_type,
                chunk.evidence_status,
                chunk.source_path,
                chunk.text,
            ),
        )
        connection.execute(
            "INSERT INTO chunks_fts(rowid, seg_text) VALUES (?, ?)",
            (cursor.lastrowid, segmented(chunk.text)),
        )
        vector = np.asarray(embedding, dtype=np.float32)
        connection.execute(
            "INSERT INTO vectors(chunk_id, dim, emb) VALUES (?, ?, ?)",
            (chunk.chunk_id, int(vector.size), vector.tobytes()),
        )


def rebuild_edges(
    connection: sqlite3.Connection, documents: list[Document]
) -> tuple[int, int]:
    """Rebuild deterministic frontmatter edges and count dangling targets."""
    known_doc_ids = {document.doc_id for document in documents}
    edges: set[tuple[str, str, str]] = set()
    missing = 0
    for document in documents:
        for target in document.related:
            if target not in known_doc_ids:
                missing += 1
                continue
            edges.add((document.doc_id, target, "related"))
    connection.execute("DELETE FROM edges")
    connection.executemany(
        "INSERT INTO edges(src_doc_id, dst_doc_id, rel) VALUES (?, ?, ?)",
        sorted(edges),
    )
    return len(edges), missing


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="rebuild every document")
    args = parser.parse_args()
    started = time.monotonic()
    root = repo_root()
    path = db_path()
    temporary = path.with_name("kb.db.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    if temporary.exists():
        temporary.unlink()
    if path.exists() and not args.full:
        shutil.copy2(path, temporary)
    connection = connect(temporary)
    create_schema(connection)
    previous_schema_row = connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    schema_changed = (
        previous_schema_row is None or previous_schema_row["value"] != SCHEMA_VERSION
    )
    has_existing_chunks = connection.execute(
        "SELECT 1 FROM chunks LIMIT 1"
    ).fetchone() is not None

    documents = [parse_document(root, path) for path in tracked_documents(root)]
    current = {document.path.as_posix(): document for document in documents}
    previous = {
        row["path"]: row["sha256"]
        for row in connection.execute("SELECT path, sha256 FROM manifest")
    }
    # Existing v2 chunks must be regenerated into semantic v3 roles even when
    # source hashes did not change.  A newly initialized/empty database has no
    # stale chunks to migrate, so a missing meta row alone must not force model
    # loading (bootstrap and diagnostics legitimately preseed only a manifest).
    force_full = args.full or (schema_changed and has_existing_chunks)
    if force_full:
        changed_paths = sorted(current)
        deleted_paths = sorted(previous)
    else:
        changed_paths = sorted(
            path for path, document in current.items() if previous.get(path) != document.sha256
        )
        deleted_paths = sorted(set(previous) - set(current))

    pending_chunks: list[Chunk] = []
    for source_path in changed_paths:
        pending_chunks.extend(chunks_for(current[source_path]))

    embeddings: list[np.ndarray] = []
    if pending_chunks:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        cache = db_path().parent / "fastembed_cache"
        try:
            model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(cache), local_files_only=True)
        except ValueError:
            os.environ.pop("HF_HUB_OFFLINE", None)
            model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(cache))
        embeddings = list(model.embed([chunk.text for chunk in pending_chunks]))

    try:
        connection.execute("BEGIN")
        if force_full:
            connection.execute("DELETE FROM chunks_fts")
            connection.execute("DELETE FROM vectors")
            connection.execute("DELETE FROM chunks")
            connection.execute("DELETE FROM manifest")
        else:
            for source_path in deleted_paths:
                delete_path(connection, source_path)
                connection.execute("DELETE FROM manifest WHERE path = ?", (source_path,))
            for source_path in changed_paths:
                delete_path(connection, source_path)
        insert_chunks(connection, pending_chunks, embeddings)
        for source_path in changed_paths:
            connection.execute(
                "INSERT OR REPLACE INTO manifest(path, sha256) VALUES (?, ?)",
                (source_path, current[source_path].sha256),
            )
        edge_count, missing_related = rebuild_edges(connection, documents)
        metadata = {
            "git_head": git_head(root) or "",
            "corpus_fingerprint": corpus_fingerprint(root),
            "model": MODEL_NAME,
            "schema_version": SCHEMA_VERSION,
            "weights": json.dumps(DEFAULT_WEIGHTS, sort_keys=True),
        }
        connection.executemany(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", metadata.items()
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    os.replace(temporary, path)

    elapsed = time.monotonic() - started
    print(
        f"build complete: docs={len(documents)} chunks={sum(len(chunks_for(doc)) for doc in documents)} "
        f"changed={len(changed_paths)} deleted={len(deleted_paths)} "
        f"edges={edge_count} missing_related={missing_related} atomic_replace={path} "
        f"elapsed={elapsed:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
