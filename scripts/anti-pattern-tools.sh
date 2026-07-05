#!/bin/bash
# ============================================================
# 反模式工具脚本(2026-05-16 起)
#
# 用法:
#   bash scripts/anti-pattern-tools.sh <command> [args]
#
# command:
#   show <id>                  显示反模式详情(id = 0090 / §3.51 / "distinctby" 模糊)
#   list [--platform X]        列所有反模式(可按端筛 Android/iOS/协调端)
#   list [--lint X]            按 lint 状态筛(done/pending/rejected/unknown)
#   add <title>                找下一空 ADR 编号 + 生成模板
#   lint-status                列所有 lint ✅/⏳/❌/❓ 分布
#   recurrence-report          列复发 ≥ 1 次的反模式(优先级)
#   help                       本帮助
# ============================================================

set +e

ROOT="<PROJECT_ROOT>"
AP_DIR="$ROOT/<docs-hub>/techspec/反模式"
INDEX="$AP_DIR/INDEX.md"
MAPPING="$AP_DIR/_mapping.json"

cmd="${1:-help}"
shift || true

case "$cmd" in

  show)
    target="$1"
    if [ -z "$target" ]; then
        echo "用法:show <0090|§3.51|关键字>"
        exit 1
    fi
    # 模式 1:ADR 4 位编号
    if [[ "$target" =~ ^[0-9]{4}$ ]]; then
        file=$(ls "$AP_DIR/${target}-"*.md 2>/dev/null | head -1)
    # 模式 2:§x.y 旧编号 → 查 mapping(支持带 § 或不带)
    elif [[ "$target" =~ ^§?[0-9]+\.[0-9]+$ ]]; then
        # 标准化为 §x.y 形式
        if [[ "$target" =~ ^[0-9] ]]; then
            legacy="§${target}"
        else
            legacy="$target"
        fi
        adr=$(python3 -c "
import json, sys
try:
    m = json.load(open('$MAPPING'))
    print(m.get(sys.argv[1], ''))
except Exception as e:
    print('', file=sys.stderr)
" "$legacy")
        if [ -n "$adr" ]; then
            file=$(ls "$AP_DIR/${adr}-"*.md 2>/dev/null | head -1)
        fi
    # 模式 3:关键字模糊匹配文件名 + INDEX 标题
    else
        file=$(ls "$AP_DIR"/*-*"$target"*.md 2>/dev/null | head -1)
        if [ -z "$file" ]; then
            # 在 INDEX 标题里模糊找
            line=$(grep -i "$target" "$INDEX" 2>/dev/null | head -1)
            adr=$(echo "$line" | grep -oE "\[([0-9]{4})\]" | head -1 | tr -d '[]')
            if [ -n "$adr" ]; then
                file=$(ls "$AP_DIR/${adr}-"*.md 2>/dev/null | head -1)
            fi
        fi
    fi

    if [ -z "$file" ] || [ ! -f "$file" ]; then
        echo "未找到 '$target' 对应反模式"
        exit 1
    fi
    echo "=== $(basename "$file") ==="
    cat "$file"
    ;;

  list)
    flag="$1"
    val="$2"
    if [ -z "$flag" ]; then
        # 全列(只标题)
        awk -F'|' '/^\| \[/{print $2 $3 $4}' "$INDEX"
    elif [ "$flag" = "--platform" ]; then
        echo "=== 端 = $val 的反模式 ==="
        awk -F'|' -v p="$val" '/^\| \[/{ if ($5 ~ p) print $2 $3 $4 $5 }' "$INDEX"
    elif [ "$flag" = "--lint" ]; then
        case "$val" in
            done) sym="✅" ;;
            pending) sym="⏳" ;;
            rejected) sym="❌" ;;
            unknown) sym="❓" ;;
            *) echo "未知 lint 状态:$val(应 done/pending/rejected/unknown)"; exit 1 ;;
        esac
        echo "=== lint $sym = $val 的反模式 ==="
        awk -F'|' -v s="$sym" '/^\| \[/{ if ($8 ~ s) print $2 $3 $4 $5 $8 }' "$INDEX"
    else
        echo "用法:list [--platform Android|iOS|协调端] [--lint done|pending|rejected|unknown]"
        exit 1
    fi
    ;;

  add)
    title="$1"
    if [ -z "$title" ]; then
        echo "用法:add \"反模式标题\""
        exit 1
    fi
    # 找下一空 ADR 编号
    last=$(ls "$AP_DIR"/*.md 2>/dev/null | xargs -I{} basename {} | grep -oE "^[0-9]{4}" | sort -n | tail -1)
    next=$(printf "%04d" $((10#$last + 1)))
    # 生成 slug(简单从标题英文短语)
    slug=$(echo "$title" | grep -oE "[A-Za-z][A-Za-z0-9-]*" | tr 'A-Z' 'a-z' | tr '\n' '-' | sed 's/-$//')
    if [ -z "$slug" ]; then
        slug="placeholder-${next}"
    fi
    new_file="$AP_DIR/${next}-${slug}.md"
    today=$(date +%Y-%m-%d)
    cat > "$new_file" << EOF
---
adr: "$next"
legacy_id: ""
title: "$title"
platforms: []
first_logged: $today
recurrence: 0
lint_status: pending
---

# $next — $title

> **首次登记**:$today
> **端**:(待补 Android / iOS / 协调端)
> **复发**:0
> **lint 状态**:⏳ TODO

---

## 现象

(描述现象,实例)

---

## 根因

1. (根因 1)
2. (根因 2)

---

## 修法

(具体修法 + 代码示例)

---

## 反例

\`\`\`
// ❌ 错误
\`\`\`

\`\`\`
// ✅ 正确
\`\`\`

---

## lint 规则草稿

\`\`\`bash
# scripts/lint/rules/XXX-${slug}.sh
\`\`\`

---

## 关联

- (相关 ADR)
- (相关 commit / handoff)
EOF
    echo "已生成 $new_file(模板)"
    echo "下一步:补完正文 + 加 frontmatter 字段后,手工更新 INDEX 或重跑 split-anti-patterns.py(不会覆盖已有)"
    ;;

  lint-status)
    echo "=== lint 状态分布 ==="
    grep -oE "lint_status: \w+" "$AP_DIR"/*.md | awk -F': ' '{print $2}' | sort | uniq -c | sort -rn
    echo ""
    echo "=== ⏳ pending(待 lint 化)清单 ==="
    grep -l "lint_status: pending" "$AP_DIR"/*.md | xargs -I{} basename {}
    ;;

  recurrence-report)
    echo "=== 复发 ≥ 1 次的反模式(按次数倒序)==="
    for f in "$AP_DIR"/*.md; do
        [[ "$(basename "$f")" == "INDEX.md" ]] && continue
        r=$(grep -oE "^recurrence: [0-9]+" "$f" | head -1 | awk '{print $2}')
        if [ -n "$r" ] && [ "$r" -gt 0 ]; then
            t=$(grep -oE '^title: ".*"' "$f" | head -1 | sed 's/title: //; s/"//g')
            echo "$r $(basename "$f"): $t"
        fi
    done | sort -rn
    ;;

  help|*)
    sed -n '3,18p' "$0"
    ;;
esac
