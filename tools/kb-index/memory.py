#!/usr/bin/env python3
"""Raw-first local session memory storage, embedding, and hybrid retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import runpy
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_annotation = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/kb/memory_annotation.py"))
normalize_annotation = _annotation["normalize"]
AnnotationConflict = _annotation["AnnotationConflict"]


MODEL_NAME = "BAAI/bge-small-zh-v1.5"
RERANK_MODEL_NAME = "BAAI/bge-reranker-base"
RERANK_CANDIDATES = 20
MAX_CONTENT = 4000
DEFAULT_LIMIT = 5
_MODEL_CACHE: dict[str, Any] = {}
_RERANKER_CACHE: dict[str, Any] = {}
_prompt_noise = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "hooks" / "lib" / "prompt_noise.py")
)
noise_category = _prompt_noise["noise_category"]
is_noise_content = _prompt_noise["is_noise_content"]
_session_identity = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "hooks" / "lib" / "session_identity.py")
)
normalize_session_identity = _session_identity["normalize_session_identity"]
normalize_source_host = _session_identity["normalize_source_host"]


# Text heuristics and pending audits are evidence, never projection authority.
TRUTH_STATES = {"current", "goal", "planned", "not_ready", "counterfactual", "uncertain", "unsupported", "unverified"}
TRUTH_SCHEMA = "sulde-graph-truth-v1"


def graph_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def source_truth(src: str, rel: str, dst: str, content: str | None,
                 declared: str = "unverified") -> dict[str, Any]:
    status = declared if declared in TRUTH_STATES else "unverified"
    if content is None:
        status = "unverified"
    return {"truth_status": status, "verified_current": False,
            "truth_basis": "unverified" if status in {"unverified", "uncertain"} else "source_bound_declaration"}


def source_review_hint(src: str, rel: str, dst: str, content: str | None) -> dict[str, str] | None:
    """Inconclusive lexical hints only; absence of hints is not verification."""
    if content is None:
        return {"temporal_modal": "uncertain", "predicate_object": "uncertain",
                "reason": "source unavailable; inconclusive review hint"}
    modal = bool(re.search(
        r"\b(?:not[ _/-]?ready|planned|planning|proposed|proposal|will|goal|aim|target|should|if|would|counterfactual|may|might)\b|"
        r"未就绪|未完成|未实现|目标|愿景|计划|提案|假如|假设|如果|反事实|可能", content, re.I))
    # Potential causal truncation, without literal triple equality.
    causal_tail = rel in {"导致", "causes", "caused"} and bool(re.search(
        re.escape(dst) + r"\s*(?:在|未|没有|without\b|to run\b)", content, re.I))
    if not modal and not causal_tail:
        return None
    return {"temporal_modal": "uncertain" if modal else "supported",
            "predicate_object": "uncertain" if causal_tail else "supported",
            "reason": "inconclusive modality/predicate hint; no projection authority"}


def edge_identity(edge: dict[str, Any]) -> dict[str, Any]:
    return {key: edge.get(key) for key in
            ("id", "src", "rel", "dst", "entry_id", "extracted_by", "confidence", "ts", "truth_status", "truth_source_sha256")}


def correction_candidate(edge: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    payload = {"schema": "sulde-graph-correction-candidate-v1", "edge": edge,
               "source_sha256": graph_digest(edge.get("content")),
               "assessment": truth, "decision": "pending_human_review", "applied": False}
    return {**payload, "candidate_sha256": graph_digest(payload)}


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def memory_db_path() -> Path:
    return kb_home() / "memory.db"


@contextmanager
def embedding_actor_lock():
    """Admit one model-loading embed writer across Hook and scheduler callers."""
    lock_path = kb_home() / "runtime" / "memory-embed.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                acquired = False
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                acquired = False
        if acquired:
            os.ftruncate(descriptor, 0)
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            os.fsync(descriptor)
        yield acquired
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def connect(
    path: Path | None = None, *, ensure_schema: bool = True
) -> sqlite3.Connection:
    connection = sqlite3.connect(path or memory_db_path(), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if ensure_schema:
        _ensure_schema(connection)
    return connection


def connect_readonly(path: Path | None = None) -> sqlite3.Connection:
    """Never create a database, migrate a schema or modify a journal on recall."""
    target = (path or memory_db_path()).expanduser().resolve()
    connection = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=0.25)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS mem_entries(
            id INTEGER PRIMARY KEY,
            project TEXT NOT NULL,
            session_id TEXT NOT NULL,
            source_host TEXT NOT NULL DEFAULT 'unknown'
                CHECK(source_host IN ('claude', 'codex', 'import', 'unknown')),
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            ts TEXT NOT NULL,
            embedded INTEGER DEFAULT 0,
            UNIQUE(session_id, content_hash)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(seg_text);
        CREATE TABLE IF NOT EXISTS mem_vectors(
            id INTEGER PRIMARY KEY REFERENCES mem_entries(id) ON DELETE CASCADE,
            dim INTEGER NOT NULL,
            vector BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mem_capture_state(
            transcript_path TEXT PRIMARY KEY,
            byte_offset INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS mem_edges(
            id INTEGER PRIMARY KEY,
            src TEXT NOT NULL,
            rel TEXT NOT NULL,
            dst TEXT NOT NULL,
            entry_id INTEGER REFERENCES mem_entries(id) ON DELETE SET NULL,
            extracted_by TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            ts TEXT NOT NULL,
            UNIQUE(src, rel, dst)
        );
        CREATE TABLE IF NOT EXISTS mem_entities(
            name TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            first_seen TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mem_annotation_receipts(
            request_sha256 TEXT PRIMARY KEY,
            request_json TEXT NOT NULL,
            result_json TEXT NOT NULL,
            ts TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS mem_entries_project ON mem_entries(project);
        CREATE INDEX IF NOT EXISTS mem_entries_session ON mem_entries(session_id, id DESC);
        CREATE INDEX IF NOT EXISTS mem_entries_pending ON mem_entries(embedded, id);
        CREATE INDEX IF NOT EXISTS mem_edges_src ON mem_edges(src, id);
        CREATE INDEX IF NOT EXISTS mem_edges_dst ON mem_edges(dst, id);
        CREATE INDEX IF NOT EXISTS mem_edges_entry ON mem_edges(entry_id, id);
        """
    )
    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(mem_entries)")
    }
    if "source_host" not in columns:
        connection.execute(
            """ALTER TABLE mem_entries ADD COLUMN source_host TEXT NOT NULL
               DEFAULT 'unknown'
               CHECK(source_host IN ('claude', 'codex', 'import', 'unknown'))"""
        )
    edge_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(mem_edges)")}
    if "truth_status" not in edge_columns:
        connection.execute("ALTER TABLE mem_edges ADD COLUMN truth_status TEXT NOT NULL "
                           "DEFAULT 'uncertain' CHECK(truth_status IN "
                           "('current','goal','planned','not_ready','counterfactual','uncertain','unsupported','unverified'))")
    if "truth_source_sha256" not in edge_columns:
        connection.execute("ALTER TABLE mem_edges ADD COLUMN truth_source_sha256 TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS mem_entries_source_host ON mem_entries(source_host, id)"
    )


def _ensure_schema(connection: sqlite3.Connection) -> None:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mem_entries'"
    ).fetchone()
    columns = (
        {str(row[1]) for row in connection.execute("PRAGMA table_info(mem_entries)")}
        if table is not None
        else set()
    )
    index = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='mem_entries_source_host'"
    ).fetchone()
    edge_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(mem_edges)")}
    receipts = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mem_annotation_receipts'").fetchone()
    if table is None or receipts is None or "source_host" not in columns or index is None or not {"truth_status", "truth_source_sha256"}.issubset(edge_columns):
        create_schema(connection)
        connection.commit()


def initialize(path: Path | None = None) -> Path:
    target = path or memory_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(target)
    try:
        connection.commit()
    finally:
        connection.close()
    return target


def segmented(text: str) -> str:
    import jieba

    return " ".join(token.strip() for token in jieba.cut_for_search(text) if token.strip())


def segmented_query(query: str) -> str:
    import jieba

    tokens = [token.strip() for token in jieba.cut_for_search(query) if token.strip()]
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def add_entry(
    connection: sqlite3.Connection,
    *,
    project: str,
    session_id: str,
    source_host: str = "unknown",
    role: str,
    content: str,
    ts: str,
    dedupe_key: str | None = None,
) -> int | None:
    """Append one raw entry and its pre-segmented FTS row; never embeds."""
    normalized = str(content).strip()[:MAX_CONTENT]
    canonical_session_id, canonical_source_host = normalize_session_identity(
        session_id, source_host
    )
    if not canonical_session_id:
        return None
    hash_input = normalized if dedupe_key is None else f"{dedupe_key}\0{normalized}"
    digest = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO mem_entries(
            project, session_id, source_host, role, content, content_hash, ts, embedded
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            project or "unknown",
            canonical_session_id,
            canonical_source_host,
            role,
            normalized,
            digest,
            ts,
        ),
    )
    if cursor.rowcount != 1:
        return None
    entry_id = int(cursor.lastrowid)
    return entry_id


def _model():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from fastembed import TextEmbedding

    # 模型缓存必须钉在持久目录——fastembed 默认落系统临时目录,会被定期清理蒸发
    cache = kb_home() / "fastembed_cache"
    key = str(cache.resolve())
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    try:
        model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(cache), local_files_only=True)
    except ValueError:
        os.environ.pop("HF_HUB_OFFLINE", None)
        model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(cache))
    _MODEL_CACHE[key] = model
    return model


def _reranker_model():
    """Load the predownloaded cross-encoder without blocking the search hot path."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    cache = kb_home() / "fastembed_cache"
    key = str(cache.resolve())
    if key in _RERANKER_CACHE:
        return _RERANKER_CACHE[key]
    # 兼容 fastembed 自有布局与 HF hub 布局(models--BAAI--bge-reranker-base)
    if not any(cache.glob("*bge-reranker*")):
        raise FileNotFoundError(f"reranker cache missing under: {cache}")
    model = TextCrossEncoder(
        model_name=RERANK_MODEL_NAME,
        cache_dir=str(cache),
        local_files_only=True,
    )
    _RERANKER_CACHE[key] = model
    return model


def _rerank_enabled() -> bool:
    return os.environ.get("SULDE_RERANK", "on").strip().lower() != "off"


def embed_pending(
    connection: sqlite3.Connection,
    *,
    limit: int | None = None,
    model: Any | None = None,
) -> int:
    import numpy as np

    sql = "SELECT id, content FROM mem_entries WHERE embedded = 0 ORDER BY id"
    parameters: list[int] = []
    if limit is not None:
        sql += " LIMIT ?"
        parameters.append(max(limit, 0))
    rows = connection.execute(sql, parameters).fetchall()
    if not rows:
        return 0
    embedding_model = model or _model()
    embeddings = embedding_model.embed([row["content"] for row in rows])
    count = 0
    with connection:
        for row, embedding in zip(rows, embeddings):
            vector = np.asarray(embedding, dtype=np.float32)
            connection.execute("DELETE FROM mem_fts WHERE rowid = ?", (row["id"],))
            connection.execute(
                "INSERT INTO mem_fts(rowid, seg_text) VALUES (?, ?)",
                (row["id"], segmented(row["content"])),
            )
            connection.execute(
                "INSERT OR REPLACE INTO mem_vectors(id, dim, vector) VALUES (?, ?, ?)",
                (row["id"], int(vector.size), vector.tobytes()),
            )
            connection.execute(
                "UPDATE mem_entries SET embedded = 1 WHERE id = ?", (row["id"],)
            )
            count += 1
    return count


def _normalize(scores: dict[int, float]) -> dict[int, float]:
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    if high - low <= 1e-12:
        return {key: 1.0 for key in scores}
    return {key: (value - low) / (high - low) for key, value in scores.items()}


def search_memory(
    query: str,
    *,
    project: str | None = None,
    limit: int = DEFAULT_LIMIT,
    session_id: str | None = None,
    exclude_recent: int = 5,
    connection: sqlite3.Connection | None = None,
    embed_pending_entries: bool = True,
) -> list[dict[str, Any]]:
    """Optionally embed pending rows, then fuse BM25 and cosine scores 0.5/0.5."""
    own_connection = connection is None
    db = connection or connect()
    try:
        # An empty store has no lexical or semantic candidates. Do not load or
        # download an embedding model just to return an empty result. A missing
        # or corrupt schema still raises; it is not treated as an empty store.
        if db.execute("SELECT 1 FROM mem_entries LIMIT 1").fetchone() is None:
            return []
        import numpy as np

        model = _model()
        if embed_pending_entries:
            embed_pending(db, model=model)
        excluded: set[int] = set()
        if session_id and exclude_recent > 0:
            excluded = {
                int(row["id"])
                for row in db.execute(
                    "SELECT id FROM mem_entries WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                    (session_id, exclude_recent),
                )
            }

        lexical: dict[int, float] = {}
        match_query = segmented_query(query)
        if match_query:
            rows = db.execute(
                """
                SELECT e.id, bm25(mem_fts) AS rank
                FROM mem_fts JOIN mem_entries e ON e.id = mem_fts.rowid
                WHERE mem_fts MATCH ? ORDER BY rank LIMIT 100
                """,
                (match_query,),
            ).fetchall()
            lexical = {
                int(row["id"]): -float(row["rank"])
                for row in rows
                if int(row["id"]) not in excluded
            }

        vector_rows = db.execute(
            "SELECT id, dim, vector FROM mem_vectors"
        ).fetchall()
        query_vector = np.asarray(next(model.query_embed(query)), dtype=np.float32)
        query_norm = float(np.linalg.norm(query_vector))
        vector_scores: dict[int, float] = {}
        for row in vector_rows:
            entry_id = int(row["id"])
            if entry_id in excluded:
                continue
            vector = np.frombuffer(row["vector"], dtype=np.float32, count=row["dim"])
            denominator = query_norm * float(np.linalg.norm(vector))
            vector_scores[entry_id] = (
                float(np.dot(query_vector, vector) / denominator) if denominator else 0.0
            )

        lexical_norm = _normalize(lexical)
        vector_top = dict(
            sorted(vector_scores.items(), key=lambda item: item[1], reverse=True)[:100]
        )
        vector_norm = _normalize(vector_top)
        candidate_ids = set(lexical_norm) | set(vector_norm)
        rows_by_id: dict[int, sqlite3.Row] = {}
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            rows_by_id = {
                int(row["id"]): row
                for row in db.execute(
                    f"SELECT * FROM mem_entries WHERE id IN ({placeholders})",
                    list(candidate_ids),
                )
            }

        ranked: list[tuple[float, int, sqlite3.Row]] = []
        for entry_id in candidate_ids:
            row = rows_by_id.get(entry_id)
            if row is None:
                continue
            score = 0.5 * lexical_norm.get(entry_id, 0.0) + 0.5 * vector_norm.get(entry_id, 0.0)
            if row["role"] == "summary":
                score *= 1.2
            # Project affinity is a deterministic tie-break, preserving comparable scores.
            project_affinity = 1 if project and row["project"] == project else 0
            ranked.append((score, project_affinity, row))
        ranked.sort(key=lambda item: (item[0], item[1], int(item[2]["id"])), reverse=True)

        rerank_scores: dict[int, float] = {}
        if ranked and _rerank_enabled():
            candidates = ranked[:RERANK_CANDIDATES]
            try:
                reranker = _reranker_model()
                raw_scores = list(
                    reranker.rerank(query, [str(item[2]["content"]) for item in candidates])
                )
                if len(raw_scores) != len(candidates):
                    raise ValueError("reranker returned an unexpected score count")
                for raw_score, (_score, _affinity, row) in zip(raw_scores, candidates):
                    value = float(raw_score)
                    if not math.isfinite(value):
                        raise ValueError("reranker returned a non-finite score")
                    if row["role"] == "summary":
                        # Cross-encoder values are logits. Adding log(1.2) applies a
                        # 1.2x odds boost without reversing the intent for negative logits.
                        value += math.log(1.2)
                    rerank_scores[int(row["id"])] = value
                candidates.sort(
                    key=lambda item: (
                        rerank_scores[int(item[2]["id"])],
                        item[1],
                        item[0],
                        int(item[2]["id"]),
                    ),
                    reverse=True,
                )
                ranked = candidates + ranked[RERANK_CANDIDATES:]
            except Exception as error:
                rerank_scores.clear()
                print(
                    "warning: local reranker unavailable; using hybrid ranking "
                    f"({type(error).__name__})",
                    file=sys.stderr,
                )

        results = []
        for score, _affinity, row in ranked[: max(limit, 0)]:
            result = {
                "id": int(row["id"]),
                "project": row["project"],
                "session_id": row["session_id"],
                "source_host": row["source_host"],
                "role": row["role"],
                "content": row["content"],
                "ts": row["ts"],
                "score": round(float(score), 6),
                # 裸余弦是绝对证据,不随候选集归一化漂移(跨项目召回门槛用)
                "cosine": round(vector_scores.get(int(row["id"]), 0.0), 6),
            }
            if rerank_scores:
                value = rerank_scores.get(int(row["id"]))
                result["rerank_score"] = None if value is None else round(value, 6)
            results.append(result)
        return results
    finally:
        if own_connection:
            db.close()


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def annotate_memory(
    connection: sqlite3.Connection,
    payload: Any,
    *,
    extracted_by: str | None = None,
) -> dict[str, Any]:
    """Atomically add compatible assertions and a durable, replayable receipt."""
    request = normalize_annotation(payload, extracted_by=extracted_by)
    request_digest = _annotation["digest"](request)
    timestamp = datetime.now(timezone.utc).isoformat()
    entities_inserted = 0
    inserted = 0
    if connection.in_transaction:
        raise ValueError("annotation requires an idle connection")
    with connection:
        # Serialize the entire read/check/write transaction, not just INSERT.
        # Never commit a caller's unrelated in-flight transaction here.
        connection.execute("BEGIN IMMEDIATE")
        previous_receipt = connection.execute(
            "SELECT 1 FROM mem_annotation_receipts WHERE request_sha256=?", (request_digest,)
        ).fetchone()
        if previous_receipt is not None:
            verified = _annotation["verify_receipt"](connection, request_digest)
            if verified is None:
                raise AnnotationConflict("previous annotation receipt no longer matches rows; human review required")
            return {**verified, "status": "already_present", "inserted": 0, "entities_inserted": 0,
                    "replayed": True}
        for entity in request["entities"]:
            previous = connection.execute("SELECT type FROM mem_entities WHERE name=?", (entity["name"],)).fetchone()
            if previous is not None and previous[0] != entity["type"]:
                raise AnnotationConflict("entity type conflicts; human review required")
            cursor = connection.execute(
                "INSERT OR IGNORE INTO mem_entities(name, type, first_seen) VALUES (?, ?, ?)",
                (entity["name"], entity["type"], timestamp),
            )
            entities_inserted += max(cursor.rowcount, 0)
        for edge in request["edges"]:
            source_digest = None
            if edge["entry_id"] is not None:
                source = connection.execute("SELECT content FROM mem_entries WHERE id=?", (edge["entry_id"],)).fetchone()
                if source is None:
                    raise ValueError("entry_id has no source")
                source_digest = graph_digest(source[0])
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO mem_edges(
                    src, rel, dst, entry_id, extracted_by, confidence, ts, truth_status, truth_source_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (edge["src"], edge["rel"], edge["dst"], edge["entry_id"], request["extracted_by"],
                 edge["confidence"], timestamp, edge["truth_status"], source_digest),
            )
            inserted += max(cursor.rowcount, 0)
        rows = _annotation["snapshot"](connection, request)
        result = {"schema": _annotation["RECEIPT_SCHEMA"], "request_sha256": request_digest,
                  "request_actor": request["extracted_by"], "rows_sha256": _annotation["digest"](rows),
                  "status": "created" if inserted or entities_inserted else "already_present",
                  "inserted": inserted, "entities_inserted": entities_inserted, "replayed": False}
        connection.execute("INSERT INTO mem_annotation_receipts VALUES (?,?,?,?)",
                           (request_digest, _annotation["canonical"](request), _annotation["canonical"](result), timestamp))
    return result


def graph_review_records(connection: sqlite3.Connection, kind: str = "graph-corrections") -> list[dict[str, Any]]:
    database = next((row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main"), "")
    if not database:
        return []
    records = []
    digest_key = "candidate_sha256" if kind == "graph-corrections" else "decision_sha256"
    for path in sorted((Path(database).parent / "governance" / kind).glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                continue
            digest = graph_digest({key: value for key, value in record.items() if key != digest_key})
            if record.get(digest_key) == digest == path.stem:
                records.append(record)
        except (OSError, ValueError, UnicodeError):
            # Broken review files cannot deny the existing relation query.
            continue
    return records


def verified_graph_decision(edge: dict[str, Any], records: list[dict[str, Any]],
                            approved_digests: tuple[str, ...]) -> dict[str, Any] | None:
    """Pins MUST come from independent human approval, never candidate files.

    Hashes establish immutability/identity, not human authorship. Explicit
    caller approval pins are the trust boundary; the default trusts none.
    Conflicting decisions require human resolution, not file ordering.
    """
    matches = []
    required = {"schema", "edge", "source_sha256", "decision", "truth_status",
                "reviewer", "reviewed_at", "decision_sha256"}
    for record in records:
        if (set(record) != required or record.get("decision_sha256") not in approved_digests
                or record.get("schema") != "sulde-graph-review-decision-v1"
                or record.get("decision") not in ("accepted", "rejected")
                or graph_digest(record.get("edge")) != graph_digest(edge_identity(edge))
                or record.get("source_sha256") != graph_digest(edge.get("content"))
                or edge.get("content") is None
                or not isinstance(record.get("reviewer"), str) or not record["reviewer"].strip()
                or not isinstance(record.get("reviewed_at"), str)
                or not isinstance(record.get("truth_status"), str)
                or record["truth_status"] not in TRUTH_STATES):
            continue
        try:
            reviewed = datetime.fromisoformat(record["reviewed_at"].replace("Z", "+00:00"))
            if reviewed.tzinfo is None or reviewed > datetime.now(timezone.utc):
                continue
        except ValueError:
            continue
        matches.append(record)
    # Rejection grants no correction; it preserves the original declaration.
    return matches[0] if len(matches) == 1 and matches[0]["decision"] == "accepted" else None


def graph_edge_truth(edge: dict[str, Any], *, decisions=(), approved_digests=()) -> dict[str, Any]:
    """One source/truth projection for explicit queries and automatic recall."""
    declared = edge.get("truth_status", "unverified")
    if edge.get("truth_source_sha256") != graph_digest(edge.get("content")):
        declared = "unverified"
    truth = source_truth(edge["src"], edge["rel"], edge["dst"], edge.get("content"), declared)
    decision = verified_graph_decision(edge, decisions, approved_digests)
    if decision is not None:
        truth.update(truth_status=decision["truth_status"], truth_basis="human_review",
                     verified_current=decision["truth_status"] == "current")
    return truth


def memory_associations(connection: sqlite3.Connection, entry_id: int, project: str, *, limit: int = 2) -> list[str]:
    """No keyless shared inference; return only source-bound current declarations.

    This automatic consumer has no independent human decision pins. A current
    declaration is consequently labelled as such, never rendered as a fact.
    """
    rows = connection.execute(
        "SELECT g.*,e.content FROM mem_edges g JOIN mem_entries e ON e.id=g.entry_id "
        "WHERE g.entry_id=? AND e.project=? ORDER BY g.id", (entry_id, project)
    )
    result = []
    for row in rows:
        edge = dict(row)
        truth = graph_edge_truth(edge)
        if truth["truth_status"] != "current":
            continue
        result.append(f"{edge['src']}-{edge['rel']}->{edge['dst']} (来源声明，未经人工核实)")
        if len(result) >= limit:
            break
    return result


def memory_graph(
    connection: sqlite3.Connection,
    entity: str,
    *,
    limit: int = 10,
    project: str | None = None,
    depth: int = 1,
    current_facts_only: bool = False,
    approved_decision_sha256: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if not 1 <= depth <= 3:
        raise ValueError("graph depth must be between 1 and 3")
    edge_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(mem_edges)")}
    truth_column = "g.truth_status" if "truth_status" in edge_columns else "'unverified'"
    digest_column = "g.truth_source_sha256" if "truth_source_sha256" in edge_columns else "NULL"
    review_records = graph_review_records(connection)
    decisions = graph_review_records(connection, "graph-decisions")
    remaining = max(limit, 0)
    results: list[dict[str, Any]] = []
    frontier = {entity}
    visited_entities = {entity}
    visited_edges: set[int] = set()
    for hop in range(1, depth + 1):
        if not frontier or remaining <= 0:
            break
        ordered_frontier = sorted(frontier)
        placeholders = ",".join("?" for _ in ordered_frontier)
        parameters: list[Any] = [*ordered_frontier, *ordered_frontier]
        project_clause = ""
        if project:
            project_clause = " AND e.project = ?"
            parameters.append(project)
        rows = connection.execute(
            f"""
            SELECT g.id, g.src, g.rel, g.dst, g.confidence, g.extracted_by,
                   g.entry_id, g.ts, e.content, {truth_column} AS truth_status,
                   {digest_column} AS truth_source_sha256
            FROM mem_edges g
            LEFT JOIN mem_entries e ON e.id = g.entry_id
            WHERE (g.src IN ({placeholders}) OR g.dst IN ({placeholders})){project_clause}
            ORDER BY g.id
            """,
            parameters,
        ).fetchall()
        next_frontier: set[str] = set()
        for row in rows:
            edge_id = int(row["id"])
            if edge_id in visited_edges:
                continue
            visited_edges.add(edge_id)
            edge = dict(row)
            truth = graph_edge_truth(edge, decisions=decisions, approved_digests=approved_decision_sha256)
            review = next((candidate for candidate in review_records
                           if candidate.get("schema") == "sulde-graph-correction-candidate-v1"
                           and isinstance(candidate.get("edge"), dict)
                           and graph_digest(edge_identity(candidate["edge"])) == graph_digest(edge_identity(edge))
                           and candidate.get("source_sha256") == graph_digest(row["content"])
                           and candidate.get("decision") == "pending_human_review"
                           and candidate.get("applied") is False), None)
            decision = verified_graph_decision(edge, decisions, approved_decision_sha256)
            if current_facts_only and truth["truth_status"] != "current":
                continue
            result = {key: row[key] for key in ("src", "rel", "dst", "confidence", "extracted_by")}
            result.update(truth)
            result["id"] = edge_id
            result["entry_id"] = row["entry_id"]
            if review is not None:
                result["review_candidate"] = review
            hint = source_review_hint(row["src"], row["rel"], row["dst"], row["content"])
            if hint is not None:
                result["review_hint"] = hint
            if decision is not None:
                result["review_decision"] = decision
            result["hop"] = hop
            results.append(result)
            remaining -= 1
            for endpoint in (str(row["src"]), str(row["dst"])):
                if endpoint not in visited_entities:
                    visited_entities.add(endpoint)
                    next_frontier.add(endpoint)
            if remaining <= 0:
                break
        frontier = next_frontier
    return results


def prune_noise(
    connection: sqlite3.Connection, *, apply: bool = False
) -> dict[str, Any]:
    """Report or transactionally delete unreferenced stored noise."""
    if apply:
        connection.execute("BEGIN IMMEDIATE")
    try:
        rows = connection.execute(
            "SELECT id, role, content FROM mem_entries ORDER BY id"
        ).fetchall()
        matches: dict[str, list[sqlite3.Row]] = {
            "notification": [],
            "image_placeholder": [],
            "system_prompt": [],
            "short": [],
        }
        for row in rows:
            # Stored summaries are durable synthesized knowledge, never prune them.
            if row["role"] == "summary":
                continue
            category = noise_category(row["content"], row["role"])
            if category is not None:
                matches[category].append(row)

        candidate_ids = [
            int(row["id"]) for values in matches.values() for row in values
        ]
        protected = {
            entry_id
            for entry_id in candidate_ids
            if connection.execute(
                "SELECT 1 FROM mem_edges WHERE entry_id = ? LIMIT 1", (entry_id,)
            ).fetchone()
        }
        deletable = [entry_id for entry_id in candidate_ids if entry_id not in protected]
        deleted = {"mem_entries": 0, "mem_fts": 0, "mem_vectors": 0}
        if apply and deletable:
            deleted["mem_fts"] = sum(
                connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM mem_fts WHERE rowid = ?)", (entry_id,)
                ).fetchone()[0]
                for entry_id in deletable
            )
            deleted["mem_vectors"] = sum(
                connection.execute(
                    "SELECT EXISTS(SELECT 1 FROM mem_vectors WHERE id = ?)", (entry_id,)
                ).fetchone()[0]
                for entry_id in deletable
            )
            connection.executemany(
                "DELETE FROM mem_fts WHERE rowid = ?", ((i,) for i in deletable)
            )
            connection.executemany(
                "DELETE FROM mem_vectors WHERE id = ?", ((i,) for i in deletable)
            )
            cursor = connection.executemany(
                "DELETE FROM mem_entries WHERE id = ?", ((i,) for i in deletable)
            )
            deleted["mem_entries"] = max(cursor.rowcount, 0)
        if apply:
            connection.commit()
        return {
            "mode": "apply" if apply else "dry-run",
            "counts": {category: len(values) for category, values in matches.items()},
            "candidates": len(candidate_ids),
            "protected": len(protected),
            "deletable": len(deletable),
            "samples": {
                category: [
                    " ".join(str(row["content"]).split())[:40]
                    for row in values[:3]
                ]
                for category, values in matches.items()
            },
            "deleted": deleted,
        }
    except Exception:
        if apply:
            connection.rollback()
        raise


def _print_prune_report(report: dict[str, Any]) -> None:
    print(
        f"mode={report['mode']} candidates={report['candidates']} "
        f"protected={report['protected']} deletable={report['deletable']}"
    )
    for category, count in report["counts"].items():
        print(f"{category}={count}")
        for sample in report["samples"][category]:
            print(f"  sample={sample}")
    deleted = report["deleted"]
    print(
        f"deleted mem_entries={deleted['mem_entries']} mem_fts={deleted['mem_fts']} "
        f"mem_vectors={deleted['mem_vectors']}"
    )


def recent_memory(
    connection: sqlite3.Connection,
    *,
    limit: int = 10,
    project: str | None = None,
    role: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    parameters: list[Any] = []
    if project:
        clauses.append("project = ?")
        parameters.append(project)
    if role:
        clauses.append("role = ?")
        parameters.append(role)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    parameters.append(max(limit, 0))
    rows = connection.execute(
        f"""
        SELECT id, ts, role, substr(content, 1, 500) AS content
        FROM mem_entries{where}
        ORDER BY ts DESC, id DESC
        LIMIT ?
        """,
        parameters,
    ).fetchall()
    return [dict(row) for row in rows]


def _load_annotation(json_value: str | None, file_path: str | None) -> Any:
    if (json_value is None) == (file_path is None):
        raise ValueError("exactly one of --json or --file is required")
    try:
        raw = json_value if json_value is not None else Path(file_path or "").read_text(encoding="utf-8")
        return json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid annotation input: {error}") from error


def _print_results(results: Iterable[dict[str, Any]], as_json: bool) -> None:
    materialized = list(results)
    if as_json:
        print(json.dumps(materialized, ensure_ascii=False, indent=2))
        return
    print("score\tts\tproject\trole\tcontent")
    for item in materialized:
        content = " ".join(str(item["content"]).split())[:200]
        print(f"{item['score']:.6f}\t{item['ts']}\t{item['project']}\t{item['role']}\t{content}")


def main() -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init")
    embed_parser = subparsers.add_parser("embed-pending")
    embed_parser.add_argument("--limit", type=int)
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("-k", "--limit", type=int, default=DEFAULT_LIMIT)
    search_parser.add_argument("--project")
    search_parser.add_argument("--session-id")
    search_parser.add_argument("--json", action="store_true")
    search_parser.add_argument(
        "--skip-pending-embed",
        action="store_true",
        help="search the current vector snapshot without writing pending embeddings",
    )
    annotate_parser = subparsers.add_parser("annotate")
    annotate_source = annotate_parser.add_mutually_exclusive_group(required=True)
    annotate_source.add_argument("--json")
    annotate_source.add_argument("--file")
    annotate_parser.add_argument(
        "--extracted-by", choices=("claude", "codex", "import"), default=None
    )
    graph_parser = subparsers.add_parser("graph")
    graph_parser.add_argument("entity")
    graph_parser.add_argument("-k", "--limit", type=int, default=10)
    graph_parser.add_argument("--project")
    graph_parser.add_argument("--current-facts-only", action="store_true", help="explicit view of source-bound current declarations or approved human facts")
    graph_parser.add_argument("--review-decision-sha256", action="append", default=[], help="independently human-approved immutable decision digest; never derive from audit candidates")
    graph_parser.add_argument("--include-noncurrent", action="store_true", help="include labeled assertions and immutable review candidates")
    graph_parser.add_argument("--depth", type=int, choices=range(1, 4), default=1)
    prune_parser = subparsers.add_parser("prune")
    prune_parser.add_argument("--noise", action="store_true", required=True)
    prune_parser.add_argument("--apply", action="store_true")
    recent_parser = subparsers.add_parser("recent")
    recent_parser.add_argument("-n", "--limit", type=int, default=10)
    recent_parser.add_argument("--project")
    recent_parser.add_argument("--role")
    args = parser.parse_args()

    if args.command == "init":
        print(f"memory schema ready: {initialize()}")
        return 0
    if not memory_db_path().is_file():
        print("memory database not found; run kb-index mem-init first", file=sys.stderr)
        return 2
    if args.command == "embed-pending":
        with embedding_actor_lock() as acquired:
            if not acquired:
                print("embedded=0 actor=already_running")
                return 0
            connection = connect()
            try:
                count = embed_pending(connection, limit=args.limit)
            finally:
                connection.close()
        print(f"embedded={count}")
        return 0
    if args.command == "search":
        _print_results(
            search_memory(
                args.query,
                project=args.project,
                limit=args.limit,
                session_id=args.session_id,
                embed_pending_entries=not args.skip_pending_embed,
            ),
            args.json,
        )
        return 0
    connection = connect_readonly() if args.command == "graph" else connect()
    try:
        if args.command != "graph":
            create_schema(connection)
        if args.command == "annotate":
            try:
                payload = _load_annotation(args.json, args.file)
                result = annotate_memory(
                    connection, payload, extracted_by=args.extracted_by
                )
            except (ValueError, sqlite3.Error) as error:
                print(str(error), file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "graph":
            print(
                json.dumps(
                    memory_graph(
                        connection,
                        args.entity,
                        limit=args.limit,
                        project=args.project,
                        depth=args.depth,
                        current_facts_only=args.current_facts_only and not args.include_noncurrent,
                        approved_decision_sha256=tuple(args.review_decision_sha256),
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "prune":
            _print_prune_report(prune_noise(connection, apply=args.apply))
            return 0
        if args.command == "recent":
            print(
                json.dumps(
                    recent_memory(
                        connection,
                        limit=args.limit,
                        project=args.project,
                        role=args.role,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
    finally:
        connection.close()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
