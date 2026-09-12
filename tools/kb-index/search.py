#!/usr/bin/env python3
"""Search the local T1.5 hybrid knowledge index."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

import jieba
import numpy as np
from fastembed import TextEmbedding

from common import (
    DEFAULT_WEIGHTS,
    MODEL_NAME,
    configure_utf8_stdio,
    connect,
    db_path,
    repo_root,
)
from search_contract import (
    PURPOSE_ROLES,
    applicability_for,
    filter_clause,
    rerank_near_ties,
)


_MODEL_CACHE: dict[tuple[str, str], TextEmbedding] = {}


def _search_model(model_name: str) -> TextEmbedding:
    cache = db_path().parent / "fastembed_cache"
    key = (model_name, str(cache.resolve()))
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    try:
        cached = TextEmbedding(
            model_name=model_name,
            cache_dir=str(cache),
            local_files_only=True,
        )
    except ValueError:
        os.environ.pop("HF_HUB_OFFLINE", None)
        cached = TextEmbedding(model_name=model_name, cache_dir=str(cache))
    _MODEL_CACHE[key] = cached
    return cached


def segmented_query(query: str) -> str:
    tokens = [token.strip() for token in jieba.cut_for_search(query) if token.strip()]
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    if high - low <= 1e-12:
        return {key: 1.0 for key in scores}
    return {key: (value - low) / (high - low) for key, value in scores.items()}


def related_results(doc_id: str, limit: int) -> list[dict[str, str]]:
    path = db_path()
    if not path.exists():
        raise FileNotFoundError("KB index database not found; run kb-index build first")
    connection = connect(path)
    try:
        rows = connection.execute(
            """
            WITH documents AS (
                SELECT doc_id, MIN(title) AS title, MIN(source_path) AS source_path
                FROM chunks
                GROUP BY doc_id
            )
            SELECT d.doc_id, d.title, d.source_path, e.rel, 'out' AS direction
            FROM edges e JOIN documents d ON d.doc_id = e.dst_doc_id
            WHERE e.src_doc_id = ?
            UNION
            SELECT d.doc_id, d.title, d.source_path, e.rel, 'in' AS direction
            FROM edges e JOIN documents d ON d.doc_id = e.src_doc_id
            WHERE e.dst_doc_id = ?
            ORDER BY doc_id, direction
            LIMIT ?
            """,
            (doc_id, doc_id, max(limit, 0)),
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def related_main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Query one-hop KB relationships.")
    parser.add_argument("doc_id")
    parser.add_argument("-k", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(arguments)
    try:
        results = related_results(args.doc_id, args.k)
    except (FileNotFoundError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("direction\trel\tdoc_id\ttitle\tsource_path")
        for item in results:
            print(
                f"{item['direction']}\t{item['rel']}\t{item['doc_id']}\t"
                f"{item['title']}\t{item['source_path']}"
            )
    return 0


def search_results(
    query: str,
    *,
    limit: int = 5,
    container: str | None = None,
    platform: str | None = None,
    purpose: str = "recall",
    connection: sqlite3.Connection | None = None,
    embedding_model: TextEmbedding | None = None,
) -> list[dict[str, object]]:
    path = db_path()
    if not path.exists():
        raise FileNotFoundError("KB index database not found; run kb-index build first")
    own_connection = connection is None
    database = connection or connect(path)
    clause, parameters = filter_clause(container, platform, purpose)

    lexical: dict[str, float] = {}
    match_query = segmented_query(query)
    if match_query:
        rows = database.execute(
            f"""
            SELECT c.chunk_id, bm25(chunks_fts) AS rank
            FROM chunks_fts
            JOIN chunks c ON c.rowid = chunks_fts.rowid
            WHERE chunks_fts MATCH ? {clause}
            ORDER BY rank LIMIT 50
            """,
            [match_query, *parameters],
        ).fetchall()
        lexical = {row["chunk_id"]: -float(row["rank"]) for row in rows}

    vector_rows = database.execute(
        f"""
        SELECT c.chunk_id, v.dim, v.emb
        FROM vectors v JOIN chunks c ON c.chunk_id = v.chunk_id
        WHERE 1 = 1 {clause}
        """,
        parameters,
    ).fetchall()
    vector_scores: dict[str, float] = {}
    if vector_rows:
        model_name_row = database.execute(
            "SELECT value FROM meta WHERE key = 'model'"
        ).fetchone()
        model_name = model_name_row["value"] if model_name_row else MODEL_NAME
        model = embedding_model or _search_model(model_name)
        query_vector = np.asarray(next(model.query_embed(query)), dtype=np.float32)
        query_norm = float(np.linalg.norm(query_vector))
        for row in vector_rows:
            vector = np.frombuffer(row["emb"], dtype=np.float32, count=row["dim"])
            denominator = query_norm * float(np.linalg.norm(vector))
            vector_scores[row["chunk_id"]] = (
                float(np.dot(query_vector, vector) / denominator) if denominator else 0.0
            )

    lexical_norm = normalize(lexical)
    vector_top = dict(
        sorted(vector_scores.items(), key=lambda item: item[1], reverse=True)[:50]
    )
    vector_norm = normalize(vector_top)
    weights_row = database.execute(
        "SELECT value FROM meta WHERE key = 'weights'"
    ).fetchone()
    weights = json.loads(weights_row["value"]) if weights_row else DEFAULT_WEIGHTS
    candidates = set(lexical_norm) | set(vector_norm)
    fused = {
        chunk_id: weights["bm25"] * lexical_norm.get(chunk_id, 0.0)
        + weights["vector"] * vector_norm.get(chunk_id, 0.0)
        for chunk_id in candidates
    }

    ranked: list[tuple[float, float, float, sqlite3.Row]] = []
    final_order = rerank_near_ties(
        (
            chunk_id,
            float(score),
            float(vector_scores.get(chunk_id, -1.0)),
        )
        for chunk_id, score in fused.items()
    )
    for chunk_id, rank_score, hybrid_score, cosine in final_order:
        row = database.execute(
            "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        if row is not None:
            ranked.append((rank_score, hybrid_score, cosine, row))
    results: list[dict[str, object]] = []
    seen_docs: set[str] = set()
    for score, hybrid_score, cosine, row in ranked:
        if row["doc_id"] in seen_docs:
            continue
        seen_docs.add(row["doc_id"])
        excerpt = " ".join(row["text"].split())[:120]
        results.append(
            {
                "doc_id": row["doc_id"],
                "title": row["title"],
                "source_path": row["source_path"],
                "container": row["container"],
                "platform": row["platform"],
                "role": row["role"],
                "applicability": applicability_for(
                    row["role"], row["evidence_status"]
                ),
                "problem_type": row["problem_type"],
                "evidence_status": row["evidence_status"] or "legacy",
                "score": round(float(score), 6),
                "hybrid_score": round(float(hybrid_score), 6),
                "cosine": round(float(cosine), 6),
                "excerpt": excerpt,
                "tier": "T1.5",
            }
        )
        if len(results) >= max(limit, 0):
            break
    if own_connection:
        database.close()
    return results


def main() -> int:
    configure_utf8_stdio()
    if len(sys.argv) > 1 and sys.argv[1] == "related":
        return related_main(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--container")
    parser.add_argument("--platform")
    parser.add_argument(
        "--purpose",
        choices=tuple(PURPOSE_ROLES),
        default="recall",
        help=(
            "route uses explicit apply/skip examples; recall includes broader diagnostic "
            "context; solution favors action/outcome sections"
        ),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        results = search_results(
            args.query,
            limit=args.k,
            container=args.container,
            platform=args.platform,
            purpose=args.purpose,
        )
    except (FileNotFoundError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("score\tdoc_id\tplatform\ttitle")
        for item in results:
            print(
                f"{item['score']:.6f}\t{item['doc_id']}\t{item['platform']}\t{item['title']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
