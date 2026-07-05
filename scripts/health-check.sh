#!/bin/bash
# ============================================================
# <project> 健康度仪表盘
#
# 用法：
#   bash scripts/health-check.sh              # 输出到 stdout + 写入 .ai-workspace/health/latest.md
#   bash scripts/health-check.sh --quiet      # 只写文件不 stdout
#   bash scripts/health-check.sh --section 3  # 只显示某 section
#
# 设计哲学（Phase 0 of 治理体系）：
#   - 不依赖任何外部工具（只用 bash / grep / awk / find）
#   - 每次跑 <5 秒
#   - 单一 markdown 报告作为"项目心跳"
#   - 可演进：每发现新漂移模式就加一个 check
#
# 覆盖检查：
#   1. 基本信息（分支 / 最近提交 / 活跃 worktree）
#   2. 三大总线状态（page-relation / 反模式 / scaffold-map）
#   3. 漂移检测（声明 ✅ 但文件不存在 / ⏳ 超期）
#   4. 基础设施（pre-commit / lint / CI / Firebase / 测试）
#   5. 待办背景（handoff / 讨论 / 备而待派）
#   6. 建议下一步（TOP 3 最紧迫动作）
# ============================================================

set +e  # 不因单个检查失败而退出

# ==== 颜色 ====
if [ -t 1 ]; then
    R='\033[31m'; G='\033[32m'; Y='\033[33m'; B='\033[34m'; C='\033[0m'; BOLD='\033[1m'
else
    R=''; G=''; Y=''; B=''; C=''; BOLD=''
fi

# ==== 路径 ====
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ANDROID="$ROOT/<android-frontend>"
IOS="$ROOT/<ios-frontend>"
DOCS="$ROOT/<docs-hub>"
TECH="$DOCS/03_技术方案"
UI_DESIGN="$DOCS/04_UI 稿"

# ==== 输出文件 ====
OUT_DIR="$ROOT/.ai-workspace/health"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/latest.md"
ARCHIVE="$OUT_DIR/$(date +%Y-%m-%d).md"

# ==== 参数 ====
QUIET=0
SECTION=""
for arg in "$@"; do
    case "$arg" in
        --quiet) QUIET=1 ;;
        --section) SECTION="next" ;;
        *)
            if [ "$SECTION" = "next" ]; then SECTION="$arg"; fi
            ;;
    esac
done

# ==== 辅助函数 ====

# 安全 grep 计数，保证返回单一数字
# 用法: count=$(grep_count 'pattern' file)
grep_count() {
    local pattern="$1"; shift
    local n
    n=$(grep -c "$pattern" "$@" 2>/dev/null)
    echo "${n:-0}"
}

# 精确 grep 计数（-E 正则）
grep_count_e() {
    local pattern="$1"; shift
    local n
    n=$(grep -cE "$pattern" "$@" 2>/dev/null)
    echo "${n:-0}"
}

# 检查文件存在
check_file() {
    [ -f "$1" ] && echo "✅" || echo "❌"
}

# 检查目录存在
check_dir() {
    [ -d "$1" ] && echo "✅" || echo "❌"
}

# ==== 开始构建报告 ====

# 全局计数
TOTAL_CHECKS=0
PASSED_CHECKS=0
DRIFT_COUNT=0
BLOCKER_COUNT=0

build_report() {

cat <<HEADER
# <project> 健康度报告

**生成时间**：$(date '+%Y-%m-%d %H:%M:%S')
**生成方式**：\`bash scripts/health-check.sh\`
**上次归档**：$(ls -1t "$OUT_DIR"/*.md 2>/dev/null | grep -v latest.md | head -1 | xargs -I{} basename {} .md 2>/dev/null || echo "无")

HEADER

# ============================================================
# Section 1: 基本信息
# ============================================================
cat <<SEC1
## 1. 基本信息

### Git 状态

| 端 | 当前分支 | 最近 commit | 活跃 worktree |
|---|---|---|:---:|
SEC1

for proj in "$ANDROID:Android" "$IOS:iOS"; do
    path="${proj%:*}"
    name="${proj#*:}"
    if [ -d "$path/.git" ] || [ -d "$path" -a -f "$path/.git" ]; then
        branch=$(cd "$path" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
        last_commit=$(cd "$path" && git log --oneline -1 2>/dev/null | head -c 60 || echo "?")
        wt_count=$(cd "$path" && git worktree list 2>/dev/null | wc -l | tr -d ' ')
        wt_count=$((wt_count - 1))  # 减去主目录
        echo "| $name | \`$branch\` | $last_commit | $wt_count |"
    else
        echo "| $name | ❌ 不是 git repo | — | — |"
    fi
done

echo ""

# ============================================================
# Section 2: 三大总线状态
# ============================================================
cat <<SEC2

## 2. 三大数据总线

### 📋 page-relation.yaml（页面关系）
SEC2

REL="$UI_DESIGN/page-relation.yaml"
if [ -f "$REL" ]; then
    total_pages=$(grep_count_e '^  "[0-9][0-9A-Za-z]*":' "$REL")
    # 页级 status 在 4-space 缩进；不要统计 android: / ios: 下的嵌套 status
    clear_count=$(grep_count_e '^    status: clear' "$REL")
    review_count=$(grep_count_e '^    status: review-needed' "$REL")
    todo_count=$(grep_count_e '^    status: todo' "$REL")
    archived_count=$(grep_count_e '^    status: archived' "$REL")
    deferred_count=$(grep_count_e '^    status: deferred-v[0-9]+' "$REL")

    echo "- 登记页面总数: **$total_pages**"
    echo "- status: clear = $clear_count"
    echo "- status: review-needed = $review_count ⚠️"
    echo "- status: todo = $todo_count ⏳"
    echo "- status: deferred-v1 = $deferred_count 📦（代码保留，首版隐藏）"
    echo "- status: archived = $archived_count"

    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    if [ "$clear_count" -gt 0 ]; then PASSED_CHECKS=$((PASSED_CHECKS + 1)); fi
else
    echo "- ❌ 文件不存在: $REL"
    BLOCKER_COUNT=$((BLOCKER_COUNT + 1))
fi

cat <<SEC2B

### 📋 反模式集合.md（已知坑）
SEC2B

ANTI="$TECH/反模式集合.md"
if [ -f "$ANTI" ]; then
    total_anti=$(grep_count_e '^### [0-9]+\.[0-9]+' "$ANTI")
    lint_green=$(grep_count '^- Android: ✅' "$ANTI")
    lint_yellow=$(grep_count '^- Android: ⏳' "$ANTI")
    recurring=$(grep_count_e '复发次数[:：][[:space:]]*[2-9]' "$ANTI")

    warn=""
    if [ "$recurring" -gt 0 ] 2>/dev/null; then warn="🔴 这些应升级 lint"; fi
    echo "- 反模式条目总数: **$total_anti**"
    echo "- Android lint 已接: $lint_green ✅"
    echo "- Android lint 待补: $lint_yellow ⏳"
    echo "- 复发 ≥ 2 次的: $recurring $warn"

    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    if [ "$total_anti" -gt 0 ]; then PASSED_CHECKS=$((PASSED_CHECKS + 1)); fi
else
    echo "- ❌ 文件不存在: $ANTI"
    BLOCKER_COUNT=$((BLOCKER_COUNT + 1))
fi

cat <<SEC2C

### 📋 scaffold-map.yaml（脚手架契约）
SEC2C

SCAFFOLD="$TECH/scaffold-map.yaml"
if [ -f "$SCAFFOLD" ]; then
    total_scaffold=$(grep_count_e '^  "[0-9]+\.[0-9]+":' "$SCAFFOLD")
    echo "- 脚手架条目: **$total_scaffold**"
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo "- ⏳ **尚未建立**（后续 Phase 2 产出物）"
    guide_marker=$(check_file "$TECH/框架脚手架规范.md")
    echo "- 已有规范文档: $guide_marker 框架脚手架规范.md"
fi

# ============================================================
# Section 3: 漂移检测
# ============================================================
cat <<SEC3

## 3. 漂移检测

### 3.1 反模式集合 ✅ 声明 vs 实际
SEC3

DRIFT_FOUND=0
if [ -f "$ANTI" ]; then
    # 提取所有声明 ✅ 的 lint 规则路径
    # 模式：- Android: ✅ \`scripts/lint/rules/XXX-xxx.sh\`
    while IFS= read -r line; do
        # 提取 scripts/lint/rules/XXX-xxx.sh 片段
        path=$(echo "$line" | grep -oE 'scripts/lint/rules/[0-9]+-[a-z0-9-]+\.sh' | head -1)
        if [ -n "$path" ]; then
            # 检查 Android 侧是否存在
            android_path="$ANDROID/$path"
            if [ ! -f "$android_path" ]; then
                echo "🔴 **漂移**: 反模式集合声明 \`$path\` 但 Android 实际不存在"
                DRIFT_FOUND=$((DRIFT_FOUND + 1))
                DRIFT_COUNT=$((DRIFT_COUNT + 1))
            fi
        fi
    done < <(grep -E '^- Android: ✅' "$ANTI" 2>/dev/null)

    if [ "$DRIFT_FOUND" -eq 0 ]; then
        echo "✅ 所有声明 ✅ 的 lint 规则文件都真实存在"
    fi
fi

cat <<SEC3B

### 3.2 page-relation.yaml 声明 vs 实际
SEC3B

DRIFT_FOUND=0
if [ -f "$REL" ]; then
    # 检查 clear 状态的 android.file
    while IFS= read -r line; do
        file=$(echo "$line" | sed -E 's/.*file:\s*//' | tr -d ' ')
        # 跳过 ?? / 相对路径前补 Android 根
        if [ -z "$file" ] || [ "$file" = "??" ]; then continue; fi
        if [[ "$file" == feature-* ]] || [[ "$file" == core-* ]] || [[ "$file" == app/* ]]; then
            full="$ANDROID/$file"
            if [ ! -f "$full" ]; then
                echo "🔴 **Android 文件不存在**: $file"
                DRIFT_FOUND=$((DRIFT_FOUND + 1))
                DRIFT_COUNT=$((DRIFT_COUNT + 1))
            fi
        fi
    done < <(grep -A 1 'android:' "$REL" 2>/dev/null | grep 'file:' | head -40)

    if [ "$DRIFT_FOUND" -eq 0 ]; then
        echo "✅ page-relation.yaml 中 Android 文件路径样本检查通过（检查 ≤40 条）"
    fi
fi

# ============================================================
# Section 4: 基础设施
# ============================================================
cat <<SEC4

## 4. 基础设施

### 🛡️ Pre-commit hooks

| 端 | 存在 | 防护数 | 大小 |
|---|:---:|:---:|:---:|
SEC4

for proj in "$ANDROID:Android" "$IOS:iOS"; do
    path="${proj%:*}"
    name="${proj#*:}"
    hook="$path/.git/hooks/pre-commit"
    if [ -f "$hook" ]; then
        defense_count=$(grep -c '^# 防护 [0-9]' "$hook" 2>/dev/null || echo "?")
        size=$(wc -c < "$hook" 2>/dev/null | tr -d ' ')
        echo "| $name | ✅ | $defense_count | ${size}B |"
        TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
        PASSED_CHECKS=$((PASSED_CHECKS + 1))
    else
        echo "| $name | ❌ | — | — |"
        BLOCKER_COUNT=$((BLOCKER_COUNT + 1))
    fi
done

cat <<SEC4B

### 🔍 Lint 规则

| 端 | 入口 | rules 数 |
|---|:---:|:---:|
SEC4B

for proj in "$ANDROID:Android" "$IOS:iOS"; do
    path="${proj%:*}"
    name="${proj#*:}"
    entry="$path/scripts/lint/lint.sh"
    rules_dir="$path/scripts/lint/rules"
    if [ -f "$entry" ]; then
        rules=$(ls -1 "$rules_dir"/*.sh 2>/dev/null | wc -l | tr -d ' ')
        echo "| $name | ✅ | $rules |"
        TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
        PASSED_CHECKS=$((PASSED_CHECKS + 1))
    else
        echo "| $name | ❌ | — |"
    fi
done

cat <<SEC4C

### 🤖 CI

| 端 | 配置 | 范围 |
|---|:---:|---|
SEC4C

for proj in "$ANDROID:Android" "$IOS:iOS"; do
    path="${proj%:*}"
    name="${proj#*:}"
    gitlab="$path/.gitlab-ci.yml"
    github="$path/.github/workflows"
    if [ -f "$gitlab" ]; then
        stages=$(grep -c '^  stage:' "$gitlab" 2>/dev/null || echo "?")
        echo "| $name | ✅ GitLab CI | $stages 个 stage |"
        TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
        PASSED_CHECKS=$((PASSED_CHECKS + 1))
    elif [ -d "$github" ]; then
        echo "| $name | ✅ GitHub Actions | — |"
        TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
        PASSED_CHECKS=$((PASSED_CHECKS + 1))
    else
        echo "| $name | ❌ 无 | — |"
    fi
done

cat <<SEC4D

### 🔥 Firebase / Crash 监控

| 端 | Crashlytics | Analytics | RemoteConfig |
|---|:---:|:---:|:---:|
SEC4D

# Android: grep build.gradle.kts
a_crash="❌"; a_analytics="❌"; a_config="❌"
if [ -f "$ANDROID/app/build.gradle.kts" ]; then
    grep -q "firebase-crashlytics\|crashlytics" "$ANDROID/app/build.gradle.kts" 2>/dev/null && a_crash="✅"
    grep -q "firebase-analytics\|firebase.analytics" "$ANDROID/app/build.gradle.kts" 2>/dev/null && a_analytics="✅"
    grep -q "firebase-config\|remoteconfig" "$ANDROID/app/build.gradle.kts" 2>/dev/null && a_config="✅"
fi
echo "| Android | $a_crash | $a_analytics | $a_config |"

# iOS: grep Package.swift
i_crash="❌"; i_analytics="❌"; i_config="❌"
if [ -f "$IOS/Package.swift" ]; then
    grep -q "FirebaseCrashlytics" "$IOS/Package.swift" 2>/dev/null && i_crash="✅"
    grep -q "FirebaseAnalytics" "$IOS/Package.swift" 2>/dev/null && i_analytics="✅"
    grep -q "FirebaseRemoteConfig" "$IOS/Package.swift" 2>/dev/null && i_config="✅"
fi
echo "| iOS | $i_crash | $i_analytics | $i_config |"

cat <<SEC4E

### 🧪 测试

| 端 | Unit/Feature Tests | 测试类数 |
|---|:---:|:---:|
SEC4E

# Android test count
android_test=0
if [ -d "$ANDROID" ]; then
    android_test=$(find "$ANDROID" -type f \( -path "*/src/test/*" -o -path "*/src/androidTest/*" \) -name "*.kt" -not -path "*/build/*" -not -path "*/.worktrees/*" 2>/dev/null | wc -l | tr -d ' ')
fi
if [ "$android_test" -gt 0 ]; then
    echo "| Android | ✅ | $android_test |"
else
    echo "| Android | ❌ **0 个测试**（阻塞级缺口） | — |"
    BLOCKER_COUNT=$((BLOCKER_COUNT + 1))
fi

# iOS test count
ios_test=0
if [ -d "$IOS/Tests" ]; then
    ios_test=$(find "$IOS/Tests" -name "*.swift" -not -path "*/.build/*" 2>/dev/null | wc -l | tr -d ' ')
fi
if [ "$ios_test" -gt 0 ]; then
    echo "| iOS | ✅ | $ios_test |"
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo "| iOS | ❌ | 0 |"
fi

# ============================================================
# Section 5: 待办积压
# ============================================================
cat <<SEC5

## 5. 待办 / 积压

### 📤 Handoff（两端转交协调端待处理）
SEC5

HANDOFF_TOTAL=0
for proj in "$ANDROID:Android" "$IOS:iOS"; do
    path="${proj%:*}"
    name="${proj#*:}"
    handoff_dir="$path/.ai-workspace/handoff"
    if [ -d "$handoff_dir" ]; then
        pending=$(ls -1 "$handoff_dir"/*.md 2>/dev/null | wc -l | tr -d ' ')
        HANDOFF_TOTAL=$((HANDOFF_TOTAL + pending))
        if [ "$pending" -gt 0 ]; then
            echo "- **$name**: $pending 份待处理"
            ls -1 "$handoff_dir"/*.md 2>/dev/null | while read f; do
                echo "  - \`$(basename "$f")\`"
            done
        else
            echo "- $name: 无"
        fi
    fi
done

if [ "$HANDOFF_TOTAL" -gt 0 ]; then
    echo ""
    echo "🔴 **协调端需处理 $HANDOFF_TOTAL 份 handoff**"
    DRIFT_COUNT=$((DRIFT_COUNT + HANDOFF_TOTAL))
fi

cat <<SEC5B

### ⏳ 备而待派任务（scaffold/）
SEC5B

TASK_TOTAL=0
for proj in "$ANDROID:Android" "$IOS:iOS"; do
    path="${proj%:*}"
    name="${proj#*:}"
    scaffold_dir="$path/.ai-workspace/tasks/scaffold"
    if [ -d "$scaffold_dir" ]; then
        count=$(ls -1 "$scaffold_dir"/*.md 2>/dev/null | wc -l | tr -d ' ')
        TASK_TOTAL=$((TASK_TOTAL + count))
        if [ "$count" -gt 0 ]; then
            echo "- **$name**: $count 份"
            ls -1 "$scaffold_dir"/*.md 2>/dev/null | while read f; do
                echo "  - \`$(basename "$f")\`"
            done
        else
            echo "- $name: 无"
        fi
    fi
done

cat <<SEC5C

### 💬 讨论清单（协调端 .ai-workspace/discussion/）
SEC5C

DISC_DIR="$ROOT/.ai-workspace/discussion"
if [ -d "$DISC_DIR" ]; then
    count=$(ls -1 "$DISC_DIR"/*.md 2>/dev/null | wc -l | tr -d ' ')
    if [ "$count" -gt 0 ]; then
        ls -1 "$DISC_DIR"/*.md 2>/dev/null | while read f; do
            echo "- \`$(basename "$f")\`"
        done
    else
        echo "- 无"
    fi
fi

# ============================================================
# Section 6: 建议下一步
# ============================================================
cat <<SEC6

## 6. 建议下一步（按紧迫度）

SEC6

NEXT_COUNT=0

# 基于上面各项状态生成推荐
if [ "$HANDOFF_TOTAL" -gt 0 ]; then
    NEXT_COUNT=$((NEXT_COUNT + 1))
    echo "**$NEXT_COUNT.** 🔴 协调端处理 $HANDOFF_TOTAL 份待归档 handoff"
fi

if [ "$DRIFT_COUNT" -gt 0 ]; then
    NEXT_COUNT=$((NEXT_COUNT + 1))
    echo "**$NEXT_COUNT.** 🔴 修复 $DRIFT_COUNT 处数据漂移（见 Section 3）"
fi

if [ "$a_crash" = "❌" ]; then
    NEXT_COUNT=$((NEXT_COUNT + 1))
    echo "**$NEXT_COUNT.** 🔴 Android 接入 Firebase Crashlytics（iOS 已接，不对称）"
fi

if [ "$android_test" = "0" ]; then
    NEXT_COUNT=$((NEXT_COUNT + 1))
    echo "**$NEXT_COUNT.** 🟡 Android 搭测试骨架（iOS 有 $ios_test 个，Android 零）"
fi

if [ ! -f "$TECH/scaffold-map.yaml" ]; then
    NEXT_COUNT=$((NEXT_COUNT + 1))
    echo "**$NEXT_COUNT.** 🟡 建立 scaffold-map.yaml（第 4 层脚手架数据化）"
fi

if [ ! -f "$IOS/.gitlab-ci.yml" ] && [ ! -d "$IOS/.github/workflows" ]; then
    NEXT_COUNT=$((NEXT_COUNT + 1))
    echo "**$NEXT_COUNT.** 🟡 iOS 加最小 CI"
fi

if [ "$TASK_TOTAL" -gt 0 ]; then
    NEXT_COUNT=$((NEXT_COUNT + 1))
    echo "**$NEXT_COUNT.** 🟢 派发 $TASK_TOTAL 份备而待派的 scaffold 任务"
fi

if [ "$NEXT_COUNT" = "0" ]; then
    echo "🎉 所有自动化检查通过，无紧迫事项。建议检查产品侧文档（见 <docs-hub>/01_战略/）。"
fi

# ============================================================
# Section 7: 总览
# ============================================================

# 计算分数
if [ "$TOTAL_CHECKS" -gt 0 ]; then
    SCORE=$((PASSED_CHECKS * 100 / TOTAL_CHECKS))
else
    SCORE=0
fi

cat <<SEC7

## 🎯 总览

| 指标 | 值 |
|-----|---|
| 自动化检查通过率 | $PASSED_CHECKS / $TOTAL_CHECKS ($SCORE%) |
| 数据漂移 | $DRIFT_COUNT |
| 阻塞级缺口 | $BLOCKER_COUNT |
| 待处理 handoff | $HANDOFF_TOTAL |
| 备而待派任务 | $TASK_TOTAL |

SEC7

if [ "$SCORE" -ge 80 ]; then
    echo "**健康度**：🟢 **$SCORE%**（发版级基线之上）"
elif [ "$SCORE" -ge 60 ]; then
    echo "**健康度**：🟡 **$SCORE%**（可用，但有短板）"
else
    echo "**健康度**：🔴 **$SCORE%**（阻塞级缺口多）"
fi

cat <<FOOTER

---

**报告位置**：\`$OUT\`
**本次归档**：\`$ARCHIVE\`

**下次运行**：直接 \`bash scripts/health-check.sh\`

下次演进本脚本时：新增 check 就加一条 + 更新 TOTAL_CHECKS / PASSED_CHECKS 计数即可。
FOOTER

}

# ==== 输出 ====
if [ "$QUIET" = "1" ]; then
    build_report > "$OUT" 2>&1
else
    build_report | tee "$OUT"
fi

# 归档当日
cp "$OUT" "$ARCHIVE" 2>/dev/null || true
