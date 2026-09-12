#!/usr/bin/env python3
"""Find document-level near duplicates in kb.db and write a proposal-only report."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import runpy
import sqlite3
import subprocess
import sys
from array import array
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote


_command_template = runpy.run_path(str(Path(__file__).with_name("command_template.py")))
split_command_template = _command_template["split_command_template"]


DEFAULT_LLM_CMD = _command_template["default_llm_command"]()
VERDICTS = {"duplicate", "distinct", "unsure"}


class DedupError(RuntimeError):
    """A controlled validation or runtime failure."""


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    source_path: str
    summary: str
    vector: tuple[float, ...]


@dataclass(frozen=True)
class Pair:
    left: str
    right: str
    similarity: float


@dataclass(frozen=True)
class Review:
    verdict: str
    retain_doc_id: str | None
    reason: str


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def readonly_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise DedupError(f"knowledge index not found: {path}")
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def decode_vector(blob: bytes, dim: int, chunk_id: str) -> tuple[float, ...]:
    if dim <= 0 or len(blob) != dim * 4:
        raise DedupError(f"invalid vector for {chunk_id}: dim={dim} bytes={len(blob)}")
    values = array("f")
    values.frombytes(blob)
    if sys.byteorder != "little":
        values.byteswap()
    if any(not math.isfinite(value) for value in values):
        raise DedupError(f"non-finite vector for {chunk_id}")
    return tuple(float(value) for value in values)


def concise_summary(texts: list[str], limit: int = 260) -> str:
    compact = " ".join(" ".join(text.split()) for text in texts if text.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def load_documents(connection: sqlite3.Connection) -> dict[str, Document]:
    try:
        rows = connection.execute(
            """
            SELECT c.chunk_id, c.doc_id, c.title, c.source_path, c.text, v.dim, v.emb
            FROM chunks AS c
            JOIN vectors AS v ON v.chunk_id = c.chunk_id
            ORDER BY c.doc_id, c.chunk_id
            """
        ).fetchall()
    except sqlite3.Error as error:
        raise DedupError(f"cannot read kb.db schema: {error}") from error
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["doc_id"], []).append(row)
    documents: dict[str, Document] = {}
    for doc_id, chunks in grouped.items():
        decoded = [decode_vector(row["emb"], int(row["dim"]), row["chunk_id"]) for row in chunks]
        dimensions = {len(vector) for vector in decoded}
        if len(dimensions) != 1:
            raise DedupError(f"mixed vector dimensions in document {doc_id}")
        mean = tuple(sum(values) / len(decoded) for values in zip(*decoded))
        norm = math.sqrt(sum(value * value for value in mean))
        if norm == 0.0:
            raise DedupError(f"zero document vector: {doc_id}")
        first = chunks[0]
        documents[doc_id] = Document(
            doc_id=doc_id,
            title=first["title"],
            source_path=first["source_path"],
            summary=concise_summary([row["text"] for row in chunks]),
            vector=tuple(value / norm for value in mean),
        )
    return documents


def load_related(connection: sqlite3.Connection) -> set[frozenset[str]]:
    try:
        rows = connection.execute("SELECT src_doc_id, dst_doc_id FROM edges WHERE rel = 'related'").fetchall()
    except sqlite3.Error as error:
        raise DedupError(f"cannot read related edges: {error}") from error
    return {
        frozenset((row["src_doc_id"], row["dst_doc_id"]))
        for row in rows
        if row["src_doc_id"] != row["dst_doc_id"]
    }


def candidate_pairs(documents: dict[str, Document], threshold: float) -> list[Pair]:
    ids = sorted(documents)
    pairs: list[Pair] = []
    for index, left_id in enumerate(ids):
        left = documents[left_id]
        for right_id in ids[index + 1 :]:
            right = documents[right_id]
            if len(left.vector) != len(right.vector):
                raise DedupError(
                    f"mixed index dimensions: {left_id}={len(left.vector)}, {right_id}={len(right.vector)}"
                )
            similarity = sum(a * b for a, b in zip(left.vector, right.vector))
            if similarity + 1e-12 >= threshold:
                pairs.append(Pair(left_id, right_id, similarity))
    return pairs


def clusters_for(pairs: list[Pair]) -> list[tuple[tuple[str, ...], tuple[Pair, ...]]]:
    parent: dict[str, str] = {}

    def find(item: str) -> str:
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for pair in pairs:
        union(pair.left, pair.right)
    members: dict[str, set[str]] = {}
    for item in parent:
        members.setdefault(find(item), set()).add(item)
    result = []
    for ids in sorted(tuple(sorted(group)) for group in members.values()):
        id_set = set(ids)
        cluster_pairs = tuple(pair for pair in pairs if pair.left in id_set and pair.right in id_set)
        result.append((ids, cluster_pairs))
    return result


def related_pairs_in_cluster(
    ids: tuple[str, ...], related: set[frozenset[str]]
) -> list[tuple[str, str]]:
    id_set = set(ids)
    pairs: list[tuple[str, str]] = []
    for edge in related:
        if len(edge) != 2 or not edge.issubset(id_set):
            continue
        left, right = sorted(edge)
        pairs.append((left, right))
    return sorted(pairs)


def run_llm(command_template: str, prompt: str) -> str:
    try:
        arguments = split_command_template(command_template)
    except ValueError as error:
        raise DedupError(f"invalid --llm-cmd: {error}") from error
    if not arguments:
        raise DedupError("--llm-cmd cannot be empty")
    stdin_prompt: str | None = prompt
    expanded: list[str] = []
    for argument in arguments:
        if argument == "{prompt}":
            continue
        if "{prompt}" in argument:
            argument = argument.replace("{prompt}", prompt)
            stdin_prompt = None
        expanded.append(argument)
    try:
        completed = subprocess.run(
            expanded,
            input=stdin_prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise DedupError(f"LLM command failed to start: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise DedupError(f"LLM command exited {completed.returncode}: {detail[:500]}")
    return completed.stdout


def review_prompt(ids: tuple[str, ...], pairs: tuple[Pair, ...], documents: dict[str, Document]) -> str:
    payload = {
        "documents": [
            {"doc_id": doc_id, "title": documents[doc_id].title, "summary": documents[doc_id].summary}
            for doc_id in ids
        ],
        "similarities": [
            {"left": pair.left, "right": pair.right, "cosine": round(pair.similarity, 6)}
            for pair in pairs
        ],
    }
    return f"""你是 Sulde 判重合并官的 headless 复核器。判断这些文档是否描述同一问题、同一根因和同一解决方案；仅主题相同但根因不同不是重复。
只输出裸 JSON，字段严格为：
{{"verdict":"duplicate|distinct|unsure","retain_doc_id":"duplicate 时必须为簇内 doc_id，否则为 null","reason":"简洁理由"}}
不得输出 Markdown 围栏或额外字段。不确定时 verdict=unsure。

候选簇：
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""


def parse_review(raw: str, ids: tuple[str, ...]) -> Review:
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[0].strip().lower() in {"```", "```json"}:
            text = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise DedupError(f"LLM output is not valid JSON: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"verdict", "retain_doc_id", "reason"}:
        raise DedupError("LLM output fields must be verdict, retain_doc_id, reason")
    verdict, retain, reason = payload["verdict"], payload["retain_doc_id"], payload["reason"]
    if verdict not in VERDICTS or not isinstance(reason, str) or not reason.strip():
        raise DedupError("LLM output contains invalid verdict or reason")
    if verdict == "duplicate":
        if retain not in ids:
            raise DedupError("duplicate review must retain a doc_id from the cluster")
    elif retain is not None:
        raise DedupError("non-duplicate review must set retain_doc_id to null")
    return Review(verdict, retain, reason.strip())


def render_report(
    *,
    threshold: float,
    documents: dict[str, Document],
    clusters: list[tuple[tuple[str, ...], tuple[Pair, ...]]],
    related: set[frozenset[str]],
    reviews: list[Review | None],
) -> str:
    duplicate_count = sum(review is not None and review.verdict == "duplicate" for review in reviews)
    series_count = sum(review is None for review in reviews)
    lines = [
        f"# 知识库近重复合并提案 — {date.today().isoformat()}",
        "",
        "> 观察员 v1：本报告只提出草案，不修改、合并或删除 knowledge 内容。",
        "",
        "## 摘要",
        "",
        f"- 阈值：余弦相似度 ≥ {threshold:.4f}",
        f"- 已索引文档：{len(documents)}",
        f"- 候选簇：{len(clusters)}",
        f"- 建议合并：{duplicate_count}",
        f"- 系列确认：{series_count}",
        "",
    ]
    for index, ((ids, pairs), review) in enumerate(zip(clusters, reviews), 1):
        lines.extend((f"## 簇 {index}", ""))
        linked_pairs = related_pairs_in_cluster(ids, related)
        if review is None:
            lines.append("- 分类：系列确认（已有 `related` 互链，不提合并）")
            lines.append("- 互链：" + ", ".join(f"`{left}` ↔ `{right}`" for left, right in linked_pairs))
            lines.append("- 建议保留：全部保留")
        else:
            labels = {
                "duplicate": "疑似重复；建议合并（待人工确认）",
                "distinct": "非重复；不合并",
                "unsure": "存疑；人工复核",
            }
            lines.append(f"- 分类：{labels[review.verdict]}")
            retained = f"`{review.retain_doc_id}`" if review.retain_doc_id else "不适用"
            lines.append(f"- 建议保留：{retained}")
            lines.append(f"- headless 复核理由：{review.reason}")
        lines.extend(("", "### 文档与摘要对照", ""))
        for doc_id in ids:
            document = documents[doc_id]
            lines.extend(
                (
                    f"- `{doc_id}` — {document.title}",
                    f"  - 来源：`{document.source_path}`",
                    f"  - 摘要：{document.summary}",
                )
            )
        lines.extend(("", "### 相似度", ""))
        for pair in sorted(pairs, key=lambda item: (-item.similarity, item.left, item.right)):
            suffix = "；related 系列" if frozenset((pair.left, pair.right)) in related else ""
            lines.append(f"- `{pair.left}` ↔ `{pair.right}`：{pair.similarity:.6f}{suffix}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--dry-run", action="store_true", help="count only; write nothing and skip LLM")
    parser.add_argument(
        "--llm-cmd",
        default=DEFAULT_LLM_CMD,
        help="command template; standalone {prompt} is sent over stdin",
    )
    args = parser.parse_args()
    if not -1.0 <= args.threshold <= 1.0:
        parser.error("--threshold must be between -1 and 1")
    return args


def execute(args: argparse.Namespace) -> int:
    home = kb_home()
    connection = readonly_connection(home / "kb.db")
    try:
        documents = load_documents(connection)
        related = load_related(connection)
    finally:
        connection.close()
    pairs = candidate_pairs(documents, args.threshold)
    clusters = clusters_for(pairs)
    series_count = sum(
        bool(related_pairs_in_cluster(ids, related)) for ids, _ in clusters
    )
    if args.dry_run:
        print(
            "DEDUP RESULT: DRY-RUN "
            f"docs={len(documents)} pairs={len(pairs)} clusters={len(clusters)} "
            f"series={series_count} threshold={args.threshold:.4f} writes=0"
        )
        return 0
    reviews: list[Review | None] = []
    for ids, cluster_pairs in clusters:
        has_related = bool(related_pairs_in_cluster(ids, related))
        if has_related:
            reviews.append(None)
            continue
        raw = run_llm(args.llm_cmd, review_prompt(ids, cluster_pairs, documents))
        reviews.append(parse_review(raw, ids))
    report_path = home / "governance" / f"dedup-{date.today().isoformat()}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            threshold=args.threshold,
            documents=documents,
            clusters=clusters,
            related=related,
            reviews=reviews,
        ),
        encoding="utf-8",
    )
    proposals = []
    for number, ((ids, cluster_pairs), review) in enumerate(zip(clusters, reviews), 1):
        proposal = {
            "schema": "sulde-dedup-review-candidate-v1", "cluster": number,
            "documents": [{"doc_id": identifier, "source_path": documents[identifier].source_path,
                           "summary": documents[identifier].summary} for identifier in ids],
            "pairs": [{"left": pair.left, "right": pair.right, "similarity": pair.similarity}
                      for pair in cluster_pairs],
            "suggestion": review.verdict if review else "related",
            "retain_doc_id": review.retain_doc_id if review else None,
            "reason": review.reason if review else "existing related links; preserve all",
            "human_confirmation_required": True, "applied": False,
        }
        digest = hashlib.sha256(json.dumps(proposal, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
        proposal["candidate_sha256"] = digest
        proposals.append(proposal)
    report_path.with_suffix(".json").write_text(json.dumps({
        "schema": "sulde-dedup-review-v1", "candidates": proposals,
        "knowledge_mutations": 0,
    }, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    duplicate_count = sum(review is not None and review.verdict == "duplicate" for review in reviews)
    print(
        "DEDUP RESULT: PASS "
        f"docs={len(documents)} pairs={len(pairs)} clusters={len(clusters)} "
        f"duplicates={duplicate_count} series={series_count} threshold={args.threshold:.4f}"
    )
    print(f"details: {report_path}")
    return 0


def main() -> int:
    try:
        return execute(parse_args())
    except DedupError as error:
        print("DEDUP RESULT: FAIL failed=1", file=sys.stderr)
        print(f"ERROR {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
