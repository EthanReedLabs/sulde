#!/usr/bin/env python3
"""
sync-shared-rules: 把 <docs-hub>/shared-rules/X.md 内容嵌入指定 CLAUDE.md 的 marker 之间。

用法:
    ./scripts/sync-shared-rules.py                       # sync 全部 rule(写)
    ./scripts/sync-shared-rules.py self-fix-boundary     # sync 单个 rule(写)
    ./scripts/sync-shared-rules.py --check               # 仅检查,有漂移 exit 1(不写)
    ./scripts/sync-shared-rules.py --check self-fix-boundary  # 检查单个

marker 格式(目标 CLAUDE.md 内):
    <!-- shared-rules:RULE_NAME ... -->
    ...content (will be replaced)...
    <!-- /shared-rules:RULE_NAME -->

shared-rule 文件首个 # 标题 + 紧随其后的 > blockquote + --- 分隔符会被自动剥离
(因为 target CLAUDE.md 已有 ## 标题)。

Exit codes:
    0 — sync 成功 / check 全部一致
    1 — check 发现漂移 / sync 失败(target 缺 marker 等)
"""
import re
import sys
from pathlib import Path

# 项目根:本脚本在 PROJECT/scripts/ 下,所以 parent.parent = PROJECT(避免硬编码,移植性)
PROJECT = Path(__file__).resolve().parent.parent
SHARED = PROJECT / "<docs-hub>/shared-rules"

# rule_name => [target relative paths]
SYNC_MAP = {
    "self-fix-boundary": [
        "<ios-frontend>/CLAUDE.md",
        "<android-frontend>/CLAUDE.md",
    ],
    # 后续扩展(预留位):
    # "model-strategy": ["<ios-frontend>/CLAUDE.md", "<android-frontend>/CLAUDE.md"],
    # "data-sources": ["<ios-frontend>/CLAUDE.md", "<android-frontend>/CLAUDE.md"],
}


def extract_body(rule_name: str) -> str:
    """读 shared-rule 内容,剥离首个 # 标题 + > blockquote + --- 分隔符,
    并把所有 markdown 标题降一级(## → ###),让嵌入后层次正确(target 的 ## 父级统辖)。
    跳过 ```code block``` 内的 #。"""
    src = SHARED / f"{rule_name}.md"
    text = src.read_text(encoding="utf-8")
    # 去首个 # 标题行
    text = re.sub(r"\A# [^\n]*\n", "", text)
    # 去紧随其后的 > blockquote 段(包括多行)+ 空行
    text = re.sub(r"\A(\s*\n)*(>[^\n]*\n)+(\s*\n)*", "", text)
    # 去首个 --- 分隔符 + 后续空行
    text = re.sub(r"\A---\s*\n+", "", text)

    # 降级所有 markdown 标题(跳过代码块内的 #)
    lines = text.split("\n")
    result = []
    in_code_block = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            result.append(line)
        elif not in_code_block:
            # ^## 或 ^### → 加一个 #
            result.append(re.sub(r"^(#+) ", lambda m: "#" + m.group(1) + " ", line))
        else:
            result.append(line)

    return "\n".join(result).strip()


def _compute_pair(rule: str, target_rel: str):
    """读 target 与 shared-rule,返回 (target_path, body, text, pattern) 或 None(若 target/source/marker 缺失)"""
    target = PROJECT / target_rel
    if not target.exists():
        print(f"  ⚠️  target 不存在: {target_rel}")
        return None

    source = SHARED / f"{rule}.md"
    if not source.exists():
        print(f"  ⚠️  source 不存在: {source}")
        return None

    body = extract_body(rule)
    text = target.read_text(encoding="utf-8")

    pattern = re.compile(
        rf"(<!--\s*shared-rules:{re.escape(rule)}\b[^>]*-->)(.*?)(<!--\s*/shared-rules:{re.escape(rule)}\s*-->)",
        re.DOTALL,
    )

    if not pattern.search(text):
        print(f"  ❌ {target_rel}: marker 未找到 (shared-rules:{rule})")
        return None

    return target, body, text, pattern


def sync_one(rule: str, target_rel: str) -> bool:
    """sync 一个 rule 到一个 target,返回是否成功"""
    pair = _compute_pair(rule, target_rel)
    if pair is None:
        return False
    target, body, text, pattern = pair

    new_text = pattern.sub(
        lambda m: f"{m.group(1)}\n\n{body}\n\n{m.group(3)}", text
    )

    if new_text == text:
        print(f"  ✓ {target_rel}: 已最新,无变化")
        return True

    target.write_text(new_text, encoding="utf-8")
    print(f"  ✅ {target_rel}: 已同步 shared-rules:{rule}")
    return True


def check_one(rule: str, target_rel: str) -> str:
    """检查 target 中 marker 之间内容是否与 shared-rule 一致。
    返回:
      - "consistent" — 一致
      - "drift"      — 漂移(shared-rule 与 marker 内容不同)
      - "config-error" — target/source 文件缺失 OR marker 未装(配置错误,非漂移)"""
    pair = _compute_pair(rule, target_rel)
    if pair is None:
        return "config-error"
    target, body, text, pattern = pair

    match = pattern.search(text)
    current = match.group(2).strip() if match else ""
    expected = body.strip()

    if current == expected:
        print(f"  ✓ {target_rel}: 一致")
        return "consistent"

    print(f"  ❌ {target_rel}: 漂移!shared-rule 与 marker 内容不一致")
    print(f"     修复:python3 scripts/sync-shared-rules.py {rule}")
    return "drift"


def main() -> int:
    args = sys.argv[1:]
    check_only = "--check" in args
    if check_only:
        args = [a for a in args if a != "--check"]

    rules = args or list(SYNC_MAP.keys())

    drift_found = False
    config_error = False
    sync_failed = False

    for rule in rules:
        if rule not in SYNC_MAP:
            print(f"❌ 未知 rule: {rule}")
            print(f"   可用: {list(SYNC_MAP.keys())}")
            return 1

        action = "check" if check_only else "sync"
        print(f"\n📋 {action} rule: {rule}")
        for target in SYNC_MAP[rule]:
            if check_only:
                result = check_one(rule, target)
                if result == "drift":
                    drift_found = True
                elif result == "config-error":
                    config_error = True
            else:
                if not sync_one(rule, target):
                    sync_failed = True

    if check_only:
        if config_error:
            print("\n❌ 配置错误 — target/source 文件缺失 OR marker 未装,先解决配置(非漂移)")
            return 1
        if drift_found:
            print("\n❌ 发现漂移 — 跑 sync 修复后再 push")
            return 1
        print("\n✅ check 通过,所有 shared-rule marker 与 source 一致")
        return 0

    if sync_failed:
        print("\n❌ 部分 sync 失败 — 见上述错误信息")
        return 1
    print("\n✅ sync 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
