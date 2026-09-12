#!/usr/bin/env python3
"""Shared Sulde sedimentation-v2 parser and semantic validator.

The contract fixes semantic roles, not Markdown presentation.  Writers may use
paragraphs, lists or tables inside a role as long as the required evidence and
sample semantics remain machine-readable.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_NAME = "sulde-sedimentation-v2"
SCHEMA_VERSION = "2"
HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")
PLACEHOLDER_RE = re.compile(r"<[^>\n]+>|\b(?:TBD|TODO|FIXME)\b", re.IGNORECASE)


class SedimentationSchemaError(ValueError):
    """The template contract itself or a v2 knowledge document is invalid."""


@dataclass(frozen=True)
class Section:
    heading: str
    level: int
    content: str


@dataclass(frozen=True)
class Sample:
    role: str
    input_text: str
    expected: str
    reason: str
    source: str


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def schema_path(root: Path | None = None) -> Path:
    return (root or repository_root()) / "templates" / "knowledge" / "schema.json"


def load_schema(root: Path | None = None) -> dict[str, Any]:
    path = schema_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SedimentationSchemaError(f"cannot read sedimentation schema: {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_NAME:
        raise SedimentationSchemaError(f"unsupported sedimentation schema: {path}")
    if payload.get("version") != int(SCHEMA_VERSION):
        raise SedimentationSchemaError(f"sedimentation schema version mismatch: {path}")
    return payload


def _scalar(raw: str) -> str:
    value = raw.strip()
    if value.startswith('"'):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, str) else str(decoded)
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def split_document(markdown: str) -> tuple[dict[str, str], str]:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    if not lines or lines[0].strip() != "---":
        raise SedimentationSchemaError("missing frontmatter at first line")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as error:
        raise SedimentationSchemaError("frontmatter is not closed") from error
    fields: dict[str, str] = {}
    for number, line in enumerate(lines[1:end], 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = FRONTMATTER_RE.match(line)
        if match is None:
            raise SedimentationSchemaError(f"frontmatter must use flat fields at line {number}")
        key, raw = match.groups()
        if key in fields:
            raise SedimentationSchemaError(f"duplicate frontmatter field: {key}")
        try:
            fields[key] = _scalar(raw or "")
        except (ValueError, json.JSONDecodeError) as error:
            raise SedimentationSchemaError(f"invalid frontmatter scalar: {key}") from error
    return fields, "\n".join(lines[end + 1 :]).strip()


def sections(markdown: str) -> list[Section]:
    _fields, body = split_document(markdown)
    matches = list(HEADING_RE.finditer(body))
    result: list[Section] = []
    for index, match in enumerate(matches):
        level = len(match.group(1))
        end = len(body)
        for following in matches[index + 1 :]:
            if len(following.group(1)) <= level:
                end = following.start()
                break
        result.append(
            Section(
                heading=match.group(2).strip(),
                level=level,
                content=body[match.end() : end].strip(),
            )
        )
    return result


def _normalized_heading(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^[0-9一二三四五六七八九十]+[.、．]\s*", "", text)
    return text.rstrip("：:").strip()


def role_for_heading(heading: str, schema: dict[str, Any] | None = None) -> str:
    contract = schema or load_schema()
    normalized = _normalized_heading(heading)
    for role, aliases in contract["roles"].items():
        if normalized in aliases:
            return str(role)
    return "general"


def _meaningful(content: str) -> str:
    text = PLACEHOLDER_RE.sub(" ", content)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"[`*_#>|\[\](){}-]", " ", text)
    return " ".join(text.split())


def _field(content: str, label: str) -> str:
    table_rows: list[list[str]] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            table_rows.append([cell.strip() for cell in stripped[1:-1].split("|")])
    if len(table_rows) >= 3:
        headers = [re.sub(r"[*_`]", "", cell).strip() for cell in table_rows[0]]
        for row in table_rows[2:]:
            if len(row) != len(headers):
                continue
            mapped = dict(zip(headers, row))
            value = mapped.get(label, "").strip()
            if value:
                return value
    pattern = re.compile(
        rf"(?:^|[\n|])\s*(?:[-*]\s*)?(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*[：:]?\s*(.+?)(?=\n|\||$)",
        re.IGNORECASE,
    )
    match = pattern.search(content)
    return match.group(1).strip() if match else ""


def extract_samples(markdown: str, schema: dict[str, Any] | None = None) -> list[Sample]:
    contract = schema or load_schema()
    by_role: dict[str, Section] = {}
    for section in sections(markdown):
        role = role_for_heading(section.heading, contract)
        if role != "general" and role not in by_role:
            by_role[role] = section
    samples: list[Sample] = []
    for role, sample_contract in contract["sample_contract"].items():
        section = by_role.get(role)
        if section is None:
            continue
        input_text = _field(section.content, str(sample_contract["input_field"]))
        expected = _field(section.content, "预期").lower()
        reason = _field(section.content, "原因")
        source = _field(section.content, "来源").lower()
        samples.append(Sample(role, input_text, expected, reason, source))
    return samples


def validate_document(
    markdown: str,
    *,
    root: Path | None = None,
    require_v2: bool = False,
) -> list[str]:
    try:
        contract = load_schema(root)
        fields, _body = split_document(markdown)
    except SedimentationSchemaError as error:
        return [str(error)]

    schema_value = fields.get("sedimentation_schema", "")
    if not require_v2 and not schema_value:
        return []
    errors: list[str] = []
    if schema_value != SCHEMA_VERSION:
        errors.append(f"sedimentation_schema must be {SCHEMA_VERSION}")
    for key in contract["frontmatter"]["required"]:
        if not fields.get(key, "").strip():
            errors.append(f"missing or empty field: {key}")
    if fields.get("problem_type") not in contract["frontmatter"]["problem_types"]:
        errors.append(f"invalid problem_type: {fields.get('problem_type', '')}")
    if fields.get("evidence_status") not in contract["frontmatter"]["evidence_statuses"]:
        errors.append(f"invalid evidence_status: {fields.get('evidence_status', '')}")

    by_role: dict[str, Section] = {}
    for section in sections(markdown):
        role = role_for_heading(section.heading, contract)
        if role != "general" and role not in by_role:
            by_role[role] = section
    for role in contract["roles"]:
        section = by_role.get(role)
        if section is None:
            errors.append(f"missing semantic section: {role}")
        elif len(_meaningful(section.content)) < 12:
            errors.append(f"semantic section has no substantive content: {role}")

    samples = {sample.role: sample for sample in extract_samples(markdown, contract)}
    for role, sample_contract in contract["sample_contract"].items():
        sample = samples.get(role)
        if sample is None:
            continue
        if len(_meaningful(sample.input_text)) < 6:
            errors.append(f"{role} is missing substantive {sample_contract['input_field']}")
        wanted = str(sample_contract["expected"])
        if sample.expected != wanted:
            errors.append(f"{role} expected must be {wanted}")
        if len(_meaningful(sample.reason)) < 6:
            errors.append(f"{role} is missing a substantive reason")
        if sample.source not in contract["sample_sources"]:
            errors.append(f"{role} source must be observed or constructed")

    if fields.get("evidence_status") == "inconclusive":
        root_cause = by_role.get("root_cause")
        uncertainty = "" if root_cause is None else root_cause.content
        if not re.search(r"inconclusive|证据不足|尚未|待验证|未确认|缺少", uncertainty, re.IGNORECASE):
            errors.append("inconclusive knowledge must state the missing evidence in root_cause")
    return errors


def guidance_excerpt(markdown: str, *, max_chars: int = 8_000) -> str:
    """Return only boundary/sample/solution roles for a semantic supervisor."""
    contract = load_schema()
    wanted = {
        "applicability",
        "route_positive",
        "route_negative",
        "outcome_positive",
        "outcome_negative",
        "solution",
    }
    blocks: list[str] = []
    for section in sections(markdown):
        if role_for_heading(section.heading, contract) in wanted:
            blocks.append(f"{'#' * section.level} {section.heading}\n\n{section.content}")
    return "\n\n".join(blocks)[:max_chars]
