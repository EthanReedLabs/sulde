#!/usr/bin/env python3
"""Small, local, deterministic knowledge growth loop for Community projects."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from sulde_runtime import SuldeCliError, atomic_write_text, resolve_within, safe_relative_path, validate_slug


FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
WORD = re.compile(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff]", re.IGNORECASE)
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "credential",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password)\b\s*[:=]\s*[\"']?[^\s\"']{6,}"
        ),
        "credential=<redacted>",
    ),
    (
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "-----BEGIN REDACTED PRIVATE KEY-----",
    ),
    (
        "home-path",
        re.compile(r"(?i)(?:/Users/|/home/|[A-Z]:\\Users\\)[^/\\\s]+"),
        "<user-home>",
    ),
    (
        "email",
        re.compile(r"\b(?![^@\s]+@example\.invalid\b)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        "<email>",
    ),
    (
        "uuid",
        re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.IGNORECASE),
        "<uuid>",
    ),
    (
        "ip-address",
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        "<ip-address>",
    ),
)


@dataclass(frozen=True)
class Document:
    path: Path
    metadata: dict[str, Any]
    body: str


def _yaml() -> Any:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SuldeCliError("PyYAML 6.0+ is required; install hooks/requirements.txt") from exc
    return yaml


def _knowledge_root(project_root: Path) -> Path:
    return resolve_within(project_root, "knowledge")


def _load_schema(knowledge_root: Path) -> dict[str, Any]:
    path = resolve_within(knowledge_root, "schema.yaml")
    try:
        value = _yaml().safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SuldeCliError("knowledge kit is not initialized; run `sulde kb init`") from exc
    except Exception as exc:
        raise SuldeCliError(f"cannot read knowledge schema: {type(exc).__name__}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("containers"), dict):
        raise SuldeCliError("knowledge/schema.yaml must define a containers mapping")
    custom_path = resolve_within(knowledge_root, "containers.json")
    if custom_path.is_file():
        try:
            custom = json.loads(custom_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SuldeCliError(f"cannot read knowledge containers registry: {type(exc).__name__}") from exc
        entries = custom.get("containers", []) if isinstance(custom, dict) else []
        if not isinstance(entries, list):
            raise SuldeCliError("knowledge containers registry must contain a list")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                raise SuldeCliError("knowledge containers registry entry is invalid")
            name = validate_slug(entry["name"])
            path_value = str(entry.get("path", f"containers/{name}"))
            safe_relative_path(path_value)
            if name in value["containers"]:
                raise SuldeCliError(f"duplicate knowledge container: {name}")
            value["containers"][name] = {
                "path": path_value,
                "description": str(entry.get("description", "Project-specific knowledge category")),
            }
    return value


def _parse_document(path: Path) -> Document:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SuldeCliError(f"cannot read {path}: {exc}") from exc
    match = FRONTMATTER.match(text)
    if match is None:
        raise SuldeCliError(f"missing YAML frontmatter: {path}")
    try:
        metadata = _yaml().safe_load(match.group(1))
    except Exception as exc:
        raise SuldeCliError(f"invalid YAML frontmatter in {path}: {type(exc).__name__}") from exc
    if not isinstance(metadata, dict):
        raise SuldeCliError(f"frontmatter must be a mapping: {path}")
    return Document(path=path, metadata=metadata, body=match.group(2))


def _iter_doc_paths(knowledge_root: Path) -> Iterable[Path]:
    ignored = {"README.md", "INDEX.md"}
    for path in sorted(knowledge_root.rglob("*.md"), key=lambda item: item.as_posix()):
        if path.name in ignored or any(part.startswith(".") for part in path.relative_to(knowledge_root).parts):
            continue
        yield path


def _documents(knowledge_root: Path, *, tolerate_errors: bool = False) -> list[Document]:
    documents: list[Document] = []
    for path in _iter_doc_paths(knowledge_root):
        try:
            documents.append(_parse_document(path))
        except SuldeCliError:
            if not tolerate_errors:
                raise
    return documents


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in WORD.finditer(text)}


def _normalized(text: str) -> str:
    return " ".join(match.group(0).lower() for match in WORD.finditer(text))


def _document_text(document: Document) -> str:
    return " ".join(
        str(document.metadata.get(key, "")) for key in ("title", "summary")
    ) + " " + document.body


def _similarity(query: str, candidate: str) -> float:
    left = _tokens(query)
    right = _tokens(candidate)
    jaccard = len(left & right) / len(left | right) if left and right else 0.0
    sequence = difflib.SequenceMatcher(None, _normalized(query), _normalized(candidate)).ratio()
    return round((jaccard * 0.7) + (sequence * 0.3), 6)


def _rank(query: str, documents: list[Document]) -> list[dict[str, Any]]:
    rows = []
    for document in documents:
        score = _similarity(query, _document_text(document))
        if score <= 0:
            continue
        rows.append(
            {
                "doc_id": str(document.metadata.get("doc_id", "")),
                "title": str(document.metadata.get("title", "")),
                "summary": str(document.metadata.get("summary", "")),
                "path": str(document.path),
                "score": score,
            }
        )
    return sorted(rows, key=lambda row: (-row["score"], row["doc_id"], row["path"]))


def _redaction_findings(text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for kind, pattern, _replacement in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0)
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
            findings.append({"kind": kind, "digest": digest})
    return findings


def _redact(text: str) -> tuple[str, list[dict[str, str]]]:
    findings = _redaction_findings(text)
    redacted = text
    for _kind, pattern, replacement in SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted, findings


def _container_info(schema: dict[str, Any], name: str) -> tuple[str, dict[str, Any]]:
    containers = schema["containers"]
    if name not in containers or not isinstance(containers[name], dict):
        raise SuldeCliError(f"unknown knowledge container: {name}")
    info = containers[name]
    raw_path = str(info.get("path", name))
    safe_relative_path(raw_path)
    return raw_path, info


def _render_document(metadata: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for key in ("doc_id", "container", "platform", "title", "summary", "status"):
        value = metadata[key]
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.extend(("---", "", body.rstrip(), ""))
    return "\n".join(lines)


def _next_path(knowledge_root: Path, container_path: str, title: str) -> tuple[Path, str]:
    base_slug = validate_slug(re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-") or "knowledge-item")
    directory = resolve_within(knowledge_root, container_path)
    candidate = resolve_within(directory, f"{base_slug}.md")
    suffix = 2
    while candidate.exists():
        candidate = resolve_within(directory, f"{base_slug}-{suffix}.md")
        suffix += 1
    return candidate, candidate.stem


def _add_document(
    knowledge_root: Path,
    *,
    container: str,
    title: str,
    summary: str,
    platform: str,
    body: str,
    status: str,
) -> Path:
    schema = _load_schema(knowledge_root)
    platforms = schema.get("platforms", [])
    if platform not in platforms:
        raise SuldeCliError(f"platform must be one of: {', '.join(map(str, platforms))}")
    container_path, _info = _container_info(schema, container)
    combined = f"{title}\n{summary}\n{body}"
    findings = _redaction_findings(combined)
    if findings:
        kinds = ", ".join(sorted({item["kind"] for item in findings}))
        raise SuldeCliError(f"redaction gate failed ({kinds}); run `sulde kb redact` first")
    ranked = _rank(combined, _documents(knowledge_root, tolerate_errors=False))
    duplicates = [row for row in ranked if row["score"] >= 0.48]
    if duplicates:
        detail = ", ".join(f"{row['doc_id']}={row['score']:.3f}" for row in duplicates[:3])
        raise SuldeCliError(f"dedup gate found likely matches: {detail}")
    path, slug = _next_path(knowledge_root, container_path, title)
    metadata = {
        "doc_id": f"{container}/{slug}",
        "container": container,
        "platform": platform,
        "title": title.strip(),
        "summary": summary.strip(),
        "status": status,
    }
    atomic_write_text(path, _render_document(metadata, body), overwrite=False)
    return path


def _body_from_path(path_value: str | None) -> str:
    if not path_value:
        return "## Problem\n\nDescribe the recurring symptom.\n\n## Cause\n\nExplain the verified root cause.\n\n## Fix\n\nDescribe the reusable fix.\n\n## Verification\n\nList objective evidence."
    path = Path(path_value).resolve()
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SuldeCliError(f"cannot read body file: {exc}") from exc


def _init(args: Any, project_root: Path) -> int:
    plugin_root = Path(args.plugin_root).resolve()
    source = resolve_within(plugin_root, "template/_project/knowledge")
    destination = _knowledge_root(project_root)
    if not source.is_dir():
        raise SuldeCliError(f"knowledge template is missing: {source}")
    created: list[str] = []
    preserved: list[str] = []
    for source_path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
        relative = source_path.relative_to(source)
        destination_path = resolve_within(destination, relative.as_posix())
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue
        if destination_path.exists():
            preserved.append(relative.as_posix())
            continue
        atomic_write_text(destination_path, source_path.read_text(encoding="utf-8"), overwrite=False)
        created.append(relative.as_posix())
    print(json.dumps({"created": created, "preserved": preserved}, ensure_ascii=False, indent=2))
    return 0


def _add(args: Any, knowledge_root: Path) -> int:
    path = _add_document(
        knowledge_root,
        container=args.container,
        title=args.title,
        summary=args.summary,
        platform=args.platform,
        body=_body_from_path(args.body),
        status="active",
    )
    print(path)
    return 0


def _dedup_or_search(args: Any, knowledge_root: Path) -> int:
    rows = _rank(args.query, _documents(knowledge_root, tolerate_errors=False))[: max(1, args.k)]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def _redact_command(args: Any, project_root: Path) -> int:
    source = Path(args.path).resolve()
    try:
        content = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SuldeCliError(f"cannot read draft: {exc}") from exc
    redacted, findings = _redact(content)
    if args.output:
        output = Path(args.output).resolve()
        if output == source:
            raise SuldeCliError("redaction output must differ from the source path")
        atomic_write_text(output, redacted, overwrite=False)
        print(json.dumps({"output": str(output), "findings": findings}, ensure_ascii=False, indent=2))
    else:
        print(redacted, end="" if redacted.endswith("\n") else "\n")
        print(json.dumps({"findings": findings}, ensure_ascii=False), file=__import__("sys").stderr)
    return 1 if findings and not args.output else 0


def _lint(knowledge_root: Path) -> int:
    schema = _load_schema(knowledge_root)
    required = schema.get("required_frontmatter", [])
    platforms = schema.get("platforms", [])
    allowed_status = schema.get("statuses", [])
    errors: list[str] = []
    seen_ids: set[str] = set()
    for path in _iter_doc_paths(knowledge_root):
        relative = path.relative_to(knowledge_root).as_posix()
        try:
            document = _parse_document(path)
        except SuldeCliError as exc:
            errors.append(str(exc))
            continue
        metadata = document.metadata
        missing = [key for key in required if not metadata.get(key)]
        if missing:
            errors.append(f"{relative}: missing {', '.join(missing)}")
        container = str(metadata.get("container", ""))
        doc_id = str(metadata.get("doc_id", ""))
        if doc_id and not doc_id.startswith(container + "/"):
            errors.append(f"{relative}: doc_id must start with {container}/")
        if doc_id in seen_ids:
            errors.append(f"{relative}: duplicate doc_id {doc_id}")
        seen_ids.add(doc_id)
        try:
            container_path, _info = _container_info(schema, container)
            expected_prefix = PurePathShim(container_path)
            if not (relative == expected_prefix or relative.startswith(expected_prefix + "/")):
                errors.append(f"{relative}: outside declared container path {container_path}")
        except SuldeCliError as exc:
            errors.append(f"{relative}: {exc}")
        if metadata.get("platform") not in platforms:
            errors.append(f"{relative}: invalid platform {metadata.get('platform')}")
        if metadata.get("status") not in allowed_status:
            errors.append(f"{relative}: invalid status {metadata.get('status')}")
        findings = _redaction_findings(path.read_text(encoding="utf-8"))
        if findings:
            errors.append(f"{relative}: redaction findings {sorted({row['kind'] for row in findings})}")
    result = {"documents": len(seen_ids), "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


def PurePathShim(value: str) -> str:
    return safe_relative_path(value).as_posix()


def _render_index(knowledge_root: Path) -> str:
    rows = []
    for document in _documents(knowledge_root, tolerate_errors=False):
        rows.append(
            (
                str(document.metadata.get("container", "")),
                str(document.metadata.get("doc_id", "")),
                str(document.metadata.get("title", "")),
                str(document.metadata.get("summary", "")),
                document.path.relative_to(knowledge_root).as_posix(),
            )
        )
    lines = ["# Knowledge Index", "", "Generated by `sulde kb index`; do not edit manually.", ""]
    current = None
    for container, doc_id, title, summary, relative in sorted(rows):
        if container != current:
            lines.extend((f"## {container}", ""))
            current = container
        lines.append(f"- [{title}]({relative}) — `{doc_id}` — {summary}")
    return "\n".join(lines).rstrip() + "\n"


def _index(args: Any, knowledge_root: Path) -> int:
    path = resolve_within(knowledge_root, "INDEX.md")
    rendered = _render_index(knowledge_root)
    if args.check:
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if current != rendered:
            print("knowledge/INDEX.md is stale")
            return 1
        print("knowledge/INDEX.md is current")
        return 0
    atomic_write_text(path, rendered)
    print(path)
    return 0


def _sediment(args: Any, knowledge_root: Path) -> int:
    source = Path(args.source).resolve()
    try:
        incident = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SuldeCliError(f"cannot read sediment source: {exc}") from exc
    if args.body:
        reusable = _body_from_path(args.body)
    else:
        reusable = (
            "## Source incident (de-identified)\n\n"
            + incident.strip()
            + "\n\n## Verified root cause\n\nTODO: replace with evidence.\n\n"
            "## Reusable fix\n\nTODO: describe the general rule.\n\n"
            "## Verification\n\nTODO: list the regression evidence."
        )
    path = _add_document(
        knowledge_root,
        container=args.container,
        title=args.title,
        summary=args.summary,
        platform=args.platform,
        body=reusable,
        status="draft",
    )
    print(json.dumps({"draft": str(path), "next": ["review TODO fields", "sulde kb lint", "sulde kb index"]}, ensure_ascii=False, indent=2))
    return 0


def command(args: Any) -> int:
    project_root = Path(args.root).resolve()
    if args.kb_command == "init":
        return _init(args, project_root)
    knowledge_root = _knowledge_root(project_root)
    handlers = {
        "add": lambda: _add(args, knowledge_root),
        "dedup": lambda: _dedup_or_search(args, knowledge_root),
        "search": lambda: _dedup_or_search(args, knowledge_root),
        "redact": lambda: _redact_command(args, project_root),
        "lint": lambda: _lint(knowledge_root),
        "index": lambda: _index(args, knowledge_root),
        "sediment": lambda: _sediment(args, knowledge_root),
    }
    return handlers[args.kb_command]()
