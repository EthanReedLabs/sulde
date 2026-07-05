#!/usr/bin/env python3
"""
反模式集合.md 批量拆分为 ADR 风格独立文件。

输入:<docs-hub>/techspec/反模式集合.md(4926 行 / 91 条)
输出:
  <docs-hub>/techspec/反模式/0001-{slug}.md ... 0091-{slug}.md
  <docs-hub>/techspec/反模式/_mapping.json(§3.51 → 0091 映射)
  <docs-hub>/techspec/反模式/INDEX.md(总索引含 metadata)

ADR 命名:按原 §x.y 出现顺序编号 0001-00NN(保持顺序)。
slug 提取:从标题英文关键字 dashed-lower-case,失败用 placeholder。
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path("<PROJECT_ROOT>")
SRC = ROOT / "<docs-hub>/techspec/反模式集合.md"
OUT_DIR = ROOT / "<docs-hub>/techspec/反模式"
MAPPING_FILE = OUT_DIR / "_mapping.json"
INDEX_FILE = OUT_DIR / "INDEX.md"


def slugify(title: str, max_len: int = 60) -> str:
    """从标题提取英文 slug。优先英文短语,失败时返回 placeholder。"""
    # 去掉前缀 §x.y / 1.1 等
    t = re.sub(r"^\s*§?\d+\.\d+\s*", "", title)
    # 去掉后缀日期 (YYYY-MM-DD) 和 (强警觉) 等附注
    t = re.sub(r"[(（][^)）]*[)）]\s*$", "", t).strip()
    # 提取英文单词(含数字 / 下划线 / 短横)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", t)
    if not tokens:
        return ""
    # 去停用词
    stop = {"a", "an", "the", "of", "in", "to", "and", "or", "is", "with"}
    tokens = [tk.lower() for tk in tokens if tk.lower() not in stop]
    if not tokens:
        return ""  # 调用方填 placeholder-XXXX
    slug = "-".join(tokens)
    # 限长
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0]
    return slug


def parse_legacy_id(title_line: str) -> str:
    """从 '### §3.51 ...' 提取 '§3.51';从 '### 1.1 ...' 提取 '§1.1'。"""
    m = re.match(r"^###?\s+(§)?(\d+)\.(\d+)", title_line)
    if not m:
        return ""
    sec = m.group(2)
    sub = m.group(3)
    return f"§{sec}.{sub}"


def parse_title(title_line: str) -> str:
    """从 '### §3.51 标题(2026-05-16)' 提取 '标题'。"""
    # 去 ### / §x.y
    t = re.sub(r"^###?\s+§?\d+\.\d+\s*", "", title_line).strip()
    # 去后缀日期
    t = re.sub(r"[(（][^)）]*[)）]\s*$", "", t).strip()
    return t


def parse_first_logged(content: str) -> str:
    """从标题行 '(YYYY-MM-DD)' 或 '**首次登记**:YYYY-MM-DD' 提取首次日期。"""
    # 优先标题日期
    m = re.search(r"[(（](20\d{2}-\d{2}-\d{2})[)）]", content[:300])
    if m:
        return m.group(1)
    # fallback **首次登记** 字段
    m = re.search(r"\*\*首次[登踩]\w*\*\*[:：]\s*(20\d{2}-\d{2}-\d{2})", content)
    if m:
        return m.group(1)
    return ""


def parse_platforms(content: str) -> list:
    """从 **端**:... 提取 [Android, iOS] / [协调端] 等。"""
    m = re.search(r"\*\*端\*\*[:：]([^\n]+)", content)
    if not m:
        return []
    raw = m.group(1)
    plats = []
    if "Android" in raw or "安卓" in raw or "A+I" in raw or re.search(r"\bA\b", raw):
        plats.append("Android")
    if "iOS" in raw or "A+I" in raw or re.search(r"\bI\b", raw):
        plats.append("iOS")
    if "协调端" in raw or "Coordinator" in raw:
        plats.append("协调端")
    return plats


def parse_recurrence(content: str) -> int:
    """从 **复发**:N 次 / **复发次数**:N 提取整数。强制 N 后跟"次"或 "(",防误抓日期。"""
    m = re.search(r"\*\*复发\w*\*\*[:：]\s*(\d+)\s*[次（(]", content)
    return int(m.group(1)) if m else 0


def parse_lint_status(content: str) -> str:
    """从 **lint 状态** 段提取 pending / done / rejected / unknown。"""
    m = re.search(r"\*\*lint 状态\*\*[:：]([^\n]+)", content)
    if not m:
        return "unknown"
    raw = m.group(1)
    if "✅" in raw or "done" in raw.lower():
        return "done"
    if "❌" in raw or "无法" in raw or "无 lint" in raw:
        return "rejected"
    if "⏳" in raw or "TODO" in raw or "待" in raw or "pending" in raw.lower():
        return "pending"
    return "unknown"


def split_sections(text: str):
    """切分文档为 (title_line, body) 段。

    段起始:^###? §?X.Y 标题(日期?)
    段结束:下一个段起始 / ## §x / EOF。
    """
    lines = text.split("\n")
    sections = []
    current_title = None
    current_body = []
    title_re = re.compile(r"^###?\s+§?(\d+)\.(\d+)\b")
    section_break_re = re.compile(r"^##\s+§?[一二三四五六七八九十]+、|^##\s+登记机制")

    for line in lines:
        # 是否新段起始
        if title_re.match(line):
            # flush 旧段
            if current_title is not None:
                sections.append((current_title, "\n".join(current_body).rstrip()))
            current_title = line
            current_body = []
        elif section_break_re.match(line):
            # 大分类标题 — flush 当前段不开启新段
            if current_title is not None:
                sections.append((current_title, "\n".join(current_body).rstrip()))
                current_title = None
                current_body = []
        elif current_title is not None:
            current_body.append(line)

    # flush 末尾
    if current_title is not None:
        sections.append((current_title, "\n".join(current_body).rstrip()))
    return sections


def yaml_list(items):
    if not items:
        return "[]"
    return "[" + ", ".join(items) + "]"


def make_frontmatter(adr_id, legacy_id, title, platforms, first_logged, recurrence, lint_status):
    escaped_title = title.replace('"', '\\"')
    first = first_logged or "unknown"
    return f"""---
adr: "{adr_id}"
legacy_id: "{legacy_id}"
title: "{escaped_title}"
platforms: {yaml_list(platforms)}
first_logged: {first}
recurrence: {recurrence}
lint_status: {lint_status}
---
"""


def main():
    if not SRC.exists():
        print(f"ERROR: {SRC} not found", file=sys.stderr)
        sys.exit(1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    text = SRC.read_text(encoding="utf-8")
    sections = split_sections(text)
    print(f"解析出 {len(sections)} 条反模式", file=sys.stderr)

    mapping = {}  # §3.51 → 0091
    index_rows = []

    for i, (title_line, body) in enumerate(sections, start=1):
        adr_id = f"{i:04d}"
        legacy_id = parse_legacy_id(title_line)
        title = parse_title(title_line)
        slug = slugify(title_line)
        # 边界:slug 含 legacy_id 数字时去掉(防 0091-3-51-xxx)
        slug = re.sub(r"^\d+-\d+-", "", slug)
        # 空 slug fallback(中文标题无英文短语)— 用 legacy_id placeholder
        if not slug:
            slug = f"placeholder-{legacy_id.replace('§', '').replace('.', '-')}"

        platforms = parse_platforms(body)
        first_logged = parse_first_logged(title_line + "\n" + body)
        recurrence = parse_recurrence(body)
        lint_status = parse_lint_status(body)

        # 输出文件
        out_name = f"{adr_id}-{slug}.md"
        out_path = OUT_DIR / out_name

        # frontmatter + 正文(body 已含原 #### 子段)
        fm = make_frontmatter(adr_id, legacy_id, title, platforms, first_logged, recurrence, lint_status)
        content = f"{fm}\n# {adr_id} — {title}\n\n> **旧编号**:{legacy_id}\n\n{body.strip()}\n"
        out_path.write_text(content, encoding="utf-8")

        mapping[legacy_id] = adr_id
        index_rows.append({
            "adr": adr_id,
            "legacy_id": legacy_id,
            "title": title,
            "platforms": platforms,
            "first_logged": first_logged,
            "recurrence": recurrence,
            "lint_status": lint_status,
            "file": out_name,
        })

    # mapping JSON
    MAPPING_FILE.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"映射表写入 {MAPPING_FILE}", file=sys.stderr)

    # INDEX.md
    lines = [
        "# 反模式 INDEX",
        "",
        f"> ADR 风格反模式索引(2026-05-16 从 反模式集合.md 拆分,见 archive)",
        f"> 共 **{len(sections)}** 条 / 各端覆盖 / lint 状态总览",
        f"> 工具:`scripts/anti-pattern-tools.sh show <0091|§3.51|distinctby>`",
        "",
        "## 总览",
        "",
        f"- 总数:{len(sections)}",
        f"- Android 涉及:{sum(1 for r in index_rows if 'Android' in r['platforms'])}",
        f"- iOS 涉及:{sum(1 for r in index_rows if 'iOS' in r['platforms'])}",
        f"- 协调端涉及:{sum(1 for r in index_rows if '协调端' in r['platforms'])}",
        f"- lint ✅ done:{sum(1 for r in index_rows if r['lint_status']=='done')}",
        f"- lint ⏳ pending:{sum(1 for r in index_rows if r['lint_status']=='pending')}",
        f"- lint ❌ rejected:{sum(1 for r in index_rows if r['lint_status']=='rejected')}",
        f"- lint ❓ unknown(老条目无字段):{sum(1 for r in index_rows if r['lint_status']=='unknown')}",
        "",
        "## 完整索引表",
        "",
        "| ADR | 旧编号 | 标题 | 端 | 首次 | 复发 | lint |",
        "|---|---|---|---|---|:-:|:-:|",
    ]
    for r in index_rows:
        plats = " / ".join(r['platforms']) if r['platforms'] else "?"
        lint = {"done": "✅", "pending": "⏳", "rejected": "❌", "unknown": "❓"}[r['lint_status']]
        lines.append(
            f"| [{r['adr']}]({r['file']}) | {r['legacy_id']} | {r['title']} | {plats} | {r['first_logged'] or '—'} | {r['recurrence']} | {lint} |"
        )
    INDEX_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"INDEX 写入 {INDEX_FILE}", file=sys.stderr)
    print(f"\n完成 — {len(sections)} 文件 + INDEX + mapping", file=sys.stderr)


if __name__ == "__main__":
    main()
