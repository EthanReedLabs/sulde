#!/bin/bash
# ============================================================
# <project> 协调端 baseline — 防止"忘记/搞混派发过的任务"
#
# 用法:
#   bash scripts/coordinator-baseline.sh          # 输出到 stdout + 写入 .ai-workspace/baseline/latest.md
#   bash scripts/coordinator-baseline.sh --quiet  # 只写文件不 stdout
#
# 设计哲学:
#   - 协调端真值数据全在磁盘(handoff archive / git log / tasks/ / coordinator-todos)
#   - 问题不是"数据没了",是"协调端 session 启动时不知道"
#   - 本脚本把真值汇总注入 SessionStart,协调端开机即拿到"历史任务全景"
#
# 覆盖检查:
#   1. 双端 active handoff(待处理 — 协调端漏处理 = 失误)
#   2. 双端 archive 最近 14 天 handoff(已完工 task 真值 — 防重复派)
#   3. 双端 develop 最近 14 天 commit(实际合并真值)
#   4. 双端 active task md(本月,未 archive — 已派但未完工)
#   5. coordinator-todos.md ⏳ / 🔴 / P0 / P1 待派
#
# 协调端 session 启动后必做:
#   - 派 task md 前 grep 历史 archive 验证不重复
#   - audit subagent prompt 必含"Step 0:Read 本 baseline + 双端实际代码"
#   - 收到 handoff 后 24h 内归档(防 active handoff 堆积)
# ============================================================

set +e

PROJECT_ROOT="<PROJECT_ROOT>"
OUT_DIR="$PROJECT_ROOT/<docs-hub>/.ai-workspace/baseline"
OUT="$OUT_DIR/latest.md"

mkdir -p "$OUT_DIR"

QUIET=0
for arg in "$@"; do
    case $arg in
        --quiet) QUIET=1 ;;
    esac
done

# 生成内容到临时文件 → 最后写 OUT(支持 --quiet 控制 stdout)
TMP=$(mktemp)

cat > "$TMP" << EOF
# <project> 协调端 baseline(防忘记/搞混派发过的任务)

**生成时间**:$(date +"%Y-%m-%d %H:%M:%S")
**生成方式**:\`bash scripts/coordinator-baseline.sh\`

> ⚠️ **协调端启动铁律**:派 task md / 派 audit subagent / 给 Dev 派单前必读本 baseline。

---

## 1. 双端 active handoff(待处理 — **协调端不能漏**)

EOF

for end in ios android; do
    echo "### ${end}" >> "$TMP"
    HANDOFF_DIR="$PROJECT_ROOT/<project>-${end}/.ai-workspace/handoff"
    if [ -d "$HANDOFF_DIR" ]; then
        ACTIVE_COUNT=$(find "$HANDOFF_DIR" -maxdepth 1 -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
        ACTIVE=$(find "$HANDOFF_DIR" -maxdepth 1 -name "*.md" -type f 2>/dev/null | sort -r | head -8)
        if [ "$ACTIVE_COUNT" -gt 0 ]; then
            if [ "$ACTIVE_COUNT" -gt 8 ]; then
                echo "**⚠️ 共 $ACTIVE_COUNT 个未归档 active handoff** — 协调端必先 sweep + 归档(显示最近 8 个):" >> "$TMP"
            fi
            echo "$ACTIVE" | while read f; do
                FNAME=$(basename "$f")
                MTIME=$(stat -f "%Sm" -t "%Y-%m-%d" "$f" 2>/dev/null || stat -c "%y" "$f" 2>/dev/null | cut -c1-10)
                echo "- ⏳ \`$FNAME\` ($MTIME)" >> "$TMP"
            done
        else
            echo "- ✅ 无 active handoff(已全部归档)" >> "$TMP"
        fi
    fi
    echo "" >> "$TMP"
done

cat >> "$TMP" << EOF
---

## 2. 双端 archive 最近 14 天 handoff(已完工 task 真值 — **派新 task md 前必 grep 验不重复**)

EOF

for end in ios android; do
    echo "### ${end}" >> "$TMP"
    ARCHIVE_DIR="$PROJECT_ROOT/<project>-${end}/.ai-workspace/handoff/archive"
    if [ -d "$ARCHIVE_DIR" ]; then
        RECENT=$(find "$ARCHIVE_DIR" -name "*.md" -mtime -14 -type f 2>/dev/null | sort -r | head -20)
        if [ -n "$RECENT" ]; then
            echo "$RECENT" | while read f; do
                FNAME=$(basename "$f")
                echo "- \`$FNAME\`" >> "$TMP"
            done
        else
            echo "- (近 14 天无归档 handoff)" >> "$TMP"
        fi
    fi
    echo "" >> "$TMP"
done

cat >> "$TMP" << EOF
---

## 3. 双端 develop 最近 14 天 commit(实际合并真值 — **凭印象想"做没做过"前必扫**)

EOF

for end in ios android; do
    echo "### ${end}" >> "$TMP"
    REPO="$PROJECT_ROOT/<project>-${end}"
    if [ -d "$REPO/.git" ]; then
        COMMITS=$(git -C "$REPO" log --oneline --since="14 days ago" develop 2>/dev/null | head -25)
        if [ -n "$COMMITS" ]; then
            echo "\`\`\`" >> "$TMP"
            echo "$COMMITS" >> "$TMP"
            echo "\`\`\`" >> "$TMP"
        else
            echo "- (无 commit)" >> "$TMP"
        fi
    fi
    echo "" >> "$TMP"
done

cat >> "$TMP" << EOF
---

## 4. 双端 active task md(本月顶层,未 archive — **已派但可能未完工**)

EOF

for end in ios android; do
    echo "### ${end}" >> "$TMP"
    TASKS_DIR="$PROJECT_ROOT/<project>-${end}/.ai-workspace/tasks"
    if [ -d "$TASKS_DIR" ]; then
        # 只看顶层(排除 archive/batch2/scaffold 子目录),近 14 天
        ACTIVE_COUNT=$(find "$TASKS_DIR" -maxdepth 1 -name "2026-05-*.md" -mtime -14 -type f 2>/dev/null | wc -l | tr -d ' ')
        ACTIVE_TASKS=$(find "$TASKS_DIR" -maxdepth 1 -name "2026-05-*.md" -mtime -14 -type f 2>/dev/null | sort -r | head -10)
        if [ "$ACTIVE_COUNT" -gt 0 ]; then
            if [ "$ACTIVE_COUNT" -gt 10 ]; then
                echo "**共 $ACTIVE_COUNT 个 active task md**(显示最近 10 个,全量看 \`ls .ai-workspace/tasks/\`):" >> "$TMP"
            fi
            echo "$ACTIVE_TASKS" | while read f; do
                FNAME=$(basename "$f")
                MTIME=$(stat -f "%Sm" -t "%Y-%m-%d" "$f" 2>/dev/null || stat -c "%y" "$f" 2>/dev/null | cut -c1-10)
                echo "- \`$FNAME\` ($MTIME)" >> "$TMP"
            done
        else
            echo "- (近 14 天无 active task md)" >> "$TMP"
        fi
    fi
    echo "" >> "$TMP"
done

cat >> "$TMP" << EOF
---

## 5. coordinator-todos.md 当前 ⏳ / 🔴 / P0 / P1 待派

EOF

TODOS="$PROJECT_ROOT/<docs-hub>/.ai-workspace/coordinator-todos.md"
if [ -f "$TODOS" ]; then
    PENDING=$(grep -E "^\- \[(⏳|🔴|P0|P1)" "$TODOS" 2>/dev/null | head -25)
    if [ -n "$PENDING" ]; then
        echo "\`\`\`" >> "$TMP"
        echo "$PENDING" >> "$TMP"
        echo "\`\`\`" >> "$TMP"
    else
        echo "- (无 ⏳ / 🔴 / P0 / P1 标记 — grep 失败或无待派)" >> "$TMP"
    fi
fi

cat >> "$TMP" << 'EOF'

## 6. 近 14 天反模式动态(协调端 session 启动必看)

EOF

ANTIPATTERN_DIR="$PROJECT_ROOT/<docs-hub>/techspec/反模式"
if [ -d "$ANTIPATTERN_DIR" ]; then
    RECENT_AP=$(find "$ANTIPATTERN_DIR" -name '0[01][0-9][0-9]-*.md' -mtime -14 2>/dev/null | sort | xargs -I {} basename {} 2>/dev/null | head -10)
    if [ -n "$RECENT_AP" ]; then
        echo "**近 14d 新增 / 更新的反模式 ADR**(协调端起草前 cross verify):" >> "$TMP"
        echo "\`\`\`" >> "$TMP"
        echo "$RECENT_AP" >> "$TMP"
        echo "\`\`\`" >> "$TMP"
        echo "" >> "$TMP"
    fi

    AP_TOTAL=$(ls "$ANTIPATTERN_DIR"/0[01][0-9][0-9]-*.md 2>/dev/null | wc -l | tr -d ' ')
    AP_COORD=$(grep -lE 'platforms: \[协调端\]|^platforms:.*协调端' "$ANTIPATTERN_DIR"/0[01][0-9][0-9]-*.md 2>/dev/null | wc -l | tr -d ' ')
    echo "**反模式 INDEX 累计**:总 $AP_TOTAL 条 / 协调端涉及 $AP_COORD 条 / ⭐ master = \`0100-coordinator-task-md-baseline-missing.md\`(协调端凭印象同源根因)" >> "$TMP"
    echo "" >> "$TMP"
    echo "**协调端起草任何 task md / pen-truth 补充段前必 cross verify §0100 master** — 详 \`writing-task-md.md §0.5\`(5 步 baseline 强制 + PreToolUse hook 实拦)" >> "$TMP"
fi

cat >> "$TMP" << 'EOF'

---

## 7. 沉淀欠债（知识库回填健康度 — forcing function）

EOF

ACTIVE_HANDOFF_TOTAL=0
for end in ios android; do
    HANDOFF_DIR="$PROJECT_ROOT/<project>-${end}/.ai-workspace/handoff"
    if [ -d "$HANDOFF_DIR" ]; then
        ACTIVE_COUNT=$(find "$HANDOFF_DIR" -maxdepth 1 -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
        [ -z "$ACTIVE_COUNT" ] && ACTIVE_COUNT=0
        ACTIVE_HANDOFF_TOTAL=$((ACTIVE_HANDOFF_TOTAL + ACTIVE_COUNT))
    fi
done

BUGBOOK_DIR="$PROJECT_ROOT/<docs-hub>/_bugbook"
if [ -d "$BUGBOOK_DIR" ]; then
    RECENT_BUGBOOK=$(find "$BUGBOOK_DIR" -name "[0-9]*.md" -mtime -30 -type f 2>/dev/null | wc -l | tr -d ' ')
else
    RECENT_BUGBOOK=0
fi
[ -z "$RECENT_BUGBOOK" ] && RECENT_BUGBOOK=0

DEBT=$((ACTIVE_HANDOFF_TOTAL - RECENT_BUGBOOK))
if [ "$DEBT" -gt 10 ]; then
    echo "⚠️ **沉淀欠债 ${DEBT}**（active handoff ${ACTIVE_HANDOFF_TOTAL} − 近30天新增 bugbook ${RECENT_BUGBOOK}）：大量修复未转入知识库 → 跑 curate 流程或逐个 add-bug 沉淀，防 Layer1 知识库冻结。" >> "$TMP"
else
    echo "- ✅ 沉淀欠债 ${DEBT}（健康；active handoff ${ACTIVE_HANDOFF_TOTAL} / 近30天 bugbook ${RECENT_BUGBOOK}）" >> "$TMP"
fi

cat >> "$TMP" << 'EOF'

---

## 协调端启动后必做(强制铁律)

| # | 时机 | 动作 |
|---|---|---|
| 1 | 收到用户问题 | 先扫上面 baseline,判断是否与已 archive 的 handoff / commit / 已派 task md 同范围 |
| 2 | 派 audit subagent 前 | subagent prompt 必含 "**Step 0:Read 协调端 baseline `<docs-hub>/.ai-workspace/baseline/latest.md` + 相关 archive handoff + git log,先回报历史,再 audit**" |
| 3 | 写 task md 前 | grep 双端 handoff archive + git log 验证"这个 endpoint / 这个 feature 是否已 wire" |
| 4 | 给 Dev 派单前 | 再扫 active handoff + active task md,防重复派 |
| 5 | 收到 Dev handoff | 24h 内 mv 到 archive/ + 更新 coordinator-todos 标完成 + 补 progress |

**违反一条 = 重复派活 / 协调端遗忘的根因(本机制就是修这个反模式 §3.45 的)**

EOF

# 写最终输出
cp "$TMP" "$OUT"
rm -f "$TMP"

# 控制 stdout
if [ "$QUIET" -eq 0 ]; then
    cat "$OUT"
fi
