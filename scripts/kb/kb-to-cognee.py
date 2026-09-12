#!/usr/bin/env python3
"""Synchronize tracked KB Markdown documents into Cognee's kb_shared dataset."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_URL = "http://localhost:8011"
DATASET_NAME = "kb_shared"
HEALTH_TIMEOUT_SECONDS = 3
POLL_INTERVAL_SECONDS = 5
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
FINISHED = {"DATASET_PROCESSING_COMPLETED", "DATASET_PROCESSING_ERRORED"}


@dataclass(frozen=True)
class Document:
    path: Path
    doc_id: str
    content: str


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def tracked_documents(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "knowledge/**/*.md"], cwd=root
    )
    paths = [
        Path(raw.decode("utf-8"))
        for raw in output.split(b"\0")
        if raw and Path(raw.decode("utf-8")).name != "INDEX.md"
    ]
    return sorted(paths, key=lambda path: path.as_posix())


def decode_scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, str) else str(decoded)
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def related_ids(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    if not (raw.startswith("[") and raw.endswith("]")):
        raise ValueError("related must be an inline list")
    inner = raw[1:-1].strip()
    if not inner:
        return []
    return [item.strip().strip("'\"") for item in inner.split(",") if item.strip()]


def parse_document(path: Path, text: str) -> Document:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}: missing frontmatter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as error:
        raise ValueError(f"{path}: unclosed frontmatter") from error

    fields: dict[str, str] = {}
    for number, line in enumerate(lines[1:end], 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = KEY_RE.match(line.rstrip("\r\n"))
        if not match:
            raise ValueError(f"{path}: malformed frontmatter at line {number}")
        key, raw_value = match.groups()
        if key in fields:
            raise ValueError(f"{path}: duplicate frontmatter field {key}")
        fields[key] = decode_scalar(raw_value or "")

    for key in ("doc_id", "container", "platform", "summary"):
        if not fields.get(key, "").strip():
            raise ValueError(f"{path}: missing or empty {key}")
    related = related_ids(fields.get("related", "[]"))
    body = "".join(lines[end + 1 :])
    title_match = H1_RE.search(body)
    if title_match is None:
        raise ValueError(f"{path}: missing H1 title")
    header = "\n".join(
        (
            f"[doc_id] {fields['doc_id']}",
            f"[container] {fields['container']}",
            f"[platform] {fields['platform']}",
            f"[title] {title_match.group(1).strip()}",
            f"[source_path] {path.as_posix()}",
            f"[related] {','.join(related)}",
        )
    )
    return Document(path=path, doc_id=fields["doc_id"], content=f"{header}\n\n{body}")


def load_documents(root: Path) -> list[Document]:
    return [
        parse_document(path, (root / path).read_text(encoding="utf-8"))
        for path in tracked_documents(root)
    ]


def request_json(
    method: str,
    path: str,
    api_key: str | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 30,
) -> Any:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=body, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload) if payload else None


def health_check() -> None:
    try:
        request = urllib.request.Request(f"{BASE_URL}/health", method="GET")
        with urllib.request.urlopen(request, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            response.read()
    except (OSError, urllib.error.URLError) as error:
        raise ConnectionError(
            f"T2 不可用: {BASE_URL}/health 在 {HEALTH_TIMEOUT_SECONDS} 秒内无有效响应: {error}"
        ) from error


def read_api_key() -> str:
    path = Path.home() / ".cognee-plugin" / "api_key.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise RuntimeError(f"无法读取 Cognee API key: {path}: {error}") from error
    api_key = value.get("api_key") if isinstance(value, dict) else None
    if not isinstance(api_key, str) or not api_key.strip():
        raise RuntimeError(f"Cognee API key 文件缺少非空 api_key 字段: {path}")
    return api_key.strip()


def multipart_body(file_path: Path) -> tuple[bytes, str]:
    boundary = f"----sulde-kb-{uuid.uuid4().hex}"
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"datasetName\"\r\n\r\n{DATASET_NAME}\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"run_in_background\"\r\n\r\ntrue\r\n",
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"data\"; "
            f"filename=\"{file_path.name}\"\r\nContent-Type: text/markdown; charset=utf-8\r\n\r\n"
        ),
    ]
    body = "".join(parts).encode("utf-8") + file_path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def remember(document: Document, api_key: str) -> None:
    safe_prefix = re.sub(r"[^A-Za-z0-9._-]", "_", document.doc_id)[:60] or "kb"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=f"{safe_prefix}-", suffix=".md"
    ) as temporary:
        temporary.write(document.content)
        temporary.flush()
        body, content_type = multipart_body(Path(temporary.name))
        request_json(
            "POST", "/api/v1/remember", api_key, body, content_type, timeout=60
        )


def dataset_status(payload: Any, dataset_name: str) -> str | None:
    if isinstance(payload, list):
        for item in payload:
            status = dataset_status(item, dataset_name)
            if status:
                return status
    elif isinstance(payload, dict):
        for key in ("datasetName", "dataset_name", "name"):
            if payload.get(key) == dataset_name:
                for status_key in ("status", "pipeline_status", "processing_status"):
                    status = payload.get(status_key)
                    if isinstance(status, str):
                        return status
        direct = payload.get(dataset_name)
        if isinstance(direct, str):
            return direct
        if isinstance(direct, dict):
            for status_key in ("status", "pipeline_status", "processing_status"):
                status = direct.get(status_key)
                if isinstance(status, str):
                    return status
        if direct is not None:
            status = dataset_status(direct, dataset_name)
            if status:
                return status
        for value in payload.values():
            status = dataset_status(value, dataset_name)
            if status:
                return status
    return None


def cognify_and_wait(api_key: str, timeout_minutes: float) -> str:
    body = json.dumps(
        {"datasets": [DATASET_NAME], "run_in_background": True}
    ).encode("utf-8")
    request_json("POST", "/api/v1/cognify", api_key, body, "application/json", timeout=60)
    deadline = time.monotonic() + timeout_minutes * 60
    while True:
        payload = request_json("GET", "/api/v1/datasets/status", api_key, timeout=30)
        status = dataset_status(payload, DATASET_NAME)
        print(f"kb_shared 状态: {status or 'UNKNOWN'}")
        if status in FINISHED:
            return status
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"等待 kb_shared 完成超过 {timeout_minutes:g} 分钟——这只是本脚本停止轮询,"
                "server 端 cognify 仍在后台继续(全量首灌实测约 60 分钟);"
                "可用 GET /api/v1/datasets/status 继续查进度,无需重跑"
            )
        time.sleep(POLL_INTERVAL_SECONDS)


def selftest() -> int:
    sample = """---
doc_id: ap-9999
container: anti-patterns
platform: none
summary: selftest
related: [ap-0001, work-model/example]
---
# 自测标题

正文第一段完整保留。

## 细节

正文第二段也完整保留。
"""
    document = parse_document(Path("knowledge/anti-patterns/9999-selftest.md"), sample)
    assert "[doc_id] ap-9999" in document.content
    assert "[source_path] knowledge/anti-patterns/9999-selftest.md" in document.content
    assert "正文第一段完整保留。" in document.content and "正文第二段也完整保留。" in document.content
    print(document.content, end="" if document.content.endswith("\n") else "\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="list tracked input without network calls")
    mode.add_argument("--selftest", action="store_true", help="verify parsing and serialization with sample text")
    parser.add_argument("--skip-cognify", action="store_true", help="remember documents without building the graph")
    parser.add_argument("--timeout-min", type=float, default=90, metavar="N", help="cognify timeout in minutes (default: 90; 290 篇全量首灌实测约 60 分钟)")
    args = parser.parse_args()
    if args.timeout_min <= 0:
        parser.error("--timeout-min must be greater than zero")
    if args.selftest:
        return selftest()
    if args.dry_run:
        try:
            documents = load_documents(repo_root())
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            print(f"KB 语料解析失败: {error}")
            return 1
        print(f"将同步 {len(documents)} 个 git tracked Markdown 文件到 {DATASET_NAME}")
        print("前 5 条 doc_id:")
        for document in documents[:5]:
            print(f"- {document.doc_id}")
        return 0

    try:
        health_check()
    except ConnectionError as error:
        print(error)
        return 2
    try:
        documents = load_documents(repo_root())
        api_key = read_api_key()
        for index, document in enumerate(documents, 1):
            remember(document, api_key)
            print(f"remember 已受理 [{index}/{len(documents)}] {document.doc_id}")
        if args.skip_cognify:
            print(f"已受理 {len(documents)} 篇文档;按 --skip-cognify 跳过图谱构建")
            return 0
        status = cognify_and_wait(api_key, args.timeout_min)
        if status == "DATASET_PROCESSING_ERRORED":
            print("kb_shared 图谱构建失败")
            return 1
        print(f"kb_shared 同步完成: {len(documents)} 篇文档")
        return 0
    except (OSError, RuntimeError, TimeoutError, ValueError, urllib.error.URLError) as error:
        print(f"kb_shared 同步失败: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
