#!/usr/bin/env python3
"""
refactor-review: 周期性扫双端代码,找编码原则集反例命中位置,输出 refactor 建议清单。

数据源:
  - <docs-hub>/techspec/编码原则集.md(双端反例集)
  - 反模式集合.md 部分 §x.y(后续扩展)

用法:
  python3 scripts/refactor-review.py                # 扫双端,输出到 .ai-workspace/refactor-review-{YYYY-MM-DD}.md
  python3 scripts/refactor-review.py --dry-run      # 只打印命中,不写文件

输出:
  .ai-workspace/refactor-review-{YYYY-MM-DD}.md(协调端审 → 决定派 task / 忽略)
"""
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
IOS = PROJECT / "<ios-frontend>" / "Sources"
ANDROID = PROJECT / "<android-frontend>"

# 反例规则:(rule_id, description, grep_pattern, file_glob, severity, suggestion, fp_patterns)
# fp_patterns: list of regex,命中行匹配任一 fp 模式则跳过(false positive 过滤)
KOTLIN_RULES = [
    ("kt-force-unwrap", "Kotlin 反例:force unwrap `!!`",
     r"!!", "*.kt", "high",
     "改 `?.` / `?:` / `let { }` 空安全链;真不可能 nil 时加注释说明",
     [
         r"_binding!!",                      # ViewBinding 标准模式
         r"private val binding get\(\)",     # ViewBinding getter 标准
         r"backDispatchCallback!!",          # AdaptiveBaseActivity 已知合法
     ]),

    ("kt-globalscope", "Kotlin 反例:`GlobalScope`(协程作用域反例)",
     r"\bGlobalScope\b", "*.kt", "high",
     "用 `viewModelScope` / `lifecycleScope` / 自定义 CoroutineScope",
     []),

    ("kt-findviewbyid", "Kotlin 反例:`findViewById`(UI 反例)",
     r"\bfindViewById\b", "*.kt", "medium",
     "改 ViewBinding(老页)或 Compose(新页);存量可暂留,新代码禁用",
     [
         r"itemView\.findViewById",          # RecyclerView ViewHolder 标准模式
         r"view\.findViewById",              # ViewHolder / 自定义 View 内部 init
     ]),

    ("kt-prefs-key-scatter", "Kotlin 反例:SharedPreferences 字符串 key 散落",
     r"prefs\.(getString|getInt|getBoolean|getLong|getFloat|edit\(\)\.(putString|putInt|putBoolean|putLong|putFloat))\(\"",
     "*.kt", "medium",
     "封 Repository(如 UserRepository / SettingsRepository),集中管理 key",
     []),

    ("kt-force-try", "Kotlin 反例:抛异常的 `requireNotNull` 散落",
     r"\brequireNotNull\(", "*.kt", "low",
     "改 `?: error(\"clear msg\")` 或在 sealed result 类型层处理",
     []),
]

SWIFT_RULES = [
    ("sw-force-unwrap-let", "Swift 反例:force unwrap 赋值 `let x = obj.value!`",
     r"^\s*let\s+\w+\s*=\s*\S+!\s*$", "*.swift", "high",
     "改 `guard let x = obj.value else { return }` 或 `if let`",
     []),

    ("sw-try-bang", "Swift 反例:`try!` 强制 try",
     r"\btry!\s", "*.swift", "high",
     "改 `try?` 或 `do/catch`",
     []),

    ("sw-nsobject-inherit", "Swift 反例:`class XxxModel: NSObject` 无理由继承",
     r"class\s+\w+Model\s*:\s*NSObject\b", "*.swift", "medium",
     "改 `struct XxxModel`(value type,免引用计数)",
     []),

    ("sw-singleton-shared", "Swift 反例:全局 Singleton `static let shared`",
     r"static\s+let\s+shared\s*=\s*\w+\(", "*.swift", "medium",
     "改 TCA `@Dependency` 或 protocol + 注入",
     [
         r"Sources/Infra\w+/",   # InfraNetwork / InfraStorage 等基础设施层合法 singleton
     ]),

    ("sw-nc-post", "Swift 反例:NotificationCenter 字符串 key 散落",
     r"NotificationCenter\.default\.post\(", "*.swift", "low",
     "改 Combine `@Published` / `@Observable` / TCA Effect",
     [
         r"Spec/LanguageService\.swift",       # 跨 module 通信无更好替代
         r"AppDelegate\.swift",                # 系统级生命周期事件
     ]),
]


def grep_rule(rule, root: Path):
    """用 grep -rEn 找规则命中,返回 [(file:line, content)]。
    macOS 自带 grep,无需 ripgrep。跳过 .ai-workspace / build / .gradle 等噪音目录。
    支持 false positive 过滤(rule[6] fp_patterns,匹配则跳过)。"""
    rule_id, desc, pattern, file_glob, severity, suggestion, fp_patterns = rule
    if not root.exists():
        return []

    try:
        result = subprocess.run(
            [
                "grep", "-rEn",
                "--include", file_glob,
                "--exclude-dir", ".ai-workspace",
                "--exclude-dir", "build",
                "--exclude-dir", ".gradle",
                "--exclude-dir", ".git",
                "--exclude-dir", "DerivedData",
                pattern,
                str(root),
            ],
            capture_output=True, text=True, timeout=60,
        )
        # grep exit: 0 = 命中,1 = 无命中,>= 2 = 错误
        if result.returncode not in (0, 1):
            return []
        hits = []
        # 编译 fp pattern(允许多个,任一匹配即视为 fp 跳过)
        fp_re = [re.compile(fp) for fp in fp_patterns]

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            # 格式: /path/file.kt:42:content
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            try:
                rel_path = Path(parts[0]).relative_to(PROJECT)
            except ValueError:
                rel_path = parts[0]
            content = parts[2].strip()
            full_loc = f"{rel_path}:{parts[1]}"
            # FP 过滤:在路径或内容中找 fp 模式
            combined = f"{rel_path}|{content}"
            if any(r.search(combined) for r in fp_re):
                continue
            hits.append((full_loc, content))
        return hits
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def scan_platform(name, root, rules):
    """扫一端,返回 {rule_id: [(file:line, content), ...]}"""
    results = {}
    for rule in rules:
        rule_id = rule[0]
        hits = grep_rule(rule, root)
        results[rule_id] = (rule, hits)
    return results


def render_report(ios_results, android_results) -> str:
    """生成 markdown 报告"""
    today = date.today().isoformat()
    lines = [
        f"# Refactor Review 报告({today})",
        "",
        f"扫描数据源:`<docs-hub>/techspec/编码原则集.md` 双端反例集",
        f"扫描对象:`<ios-frontend>/Sources/` + `<android-frontend>/`",
        "",
        "---",
        "",
    ]

    for platform, results in [("Kotlin / Android", android_results), ("Swift / iOS", ios_results)]:
        lines.append(f"## {platform} 反例命中")
        lines.append("")

        total_hits = sum(len(hits) for _, (_, hits) in results.items())
        if total_hits == 0:
            lines.append("✅ 全部反例 0 命中")
            lines.append("")
            continue

        # 按命中数排序
        sorted_rules = sorted(results.items(), key=lambda x: -len(x[1][1]))

        for rule_id, (rule, hits) in sorted_rules:
            _, desc, pattern, file_glob, severity, suggestion, _ = rule
            count = len(hits)
            icon = "🔴" if severity == "high" and count > 0 else "🟡" if count > 0 else "✅"
            lines.append(f"### {icon} `{rule_id}` — {desc}")
            lines.append(f"**命中**:{count} 处 / **严重度**:{severity}")
            lines.append(f"**建议**:{suggestion}")
            lines.append("")
            if count > 0:
                lines.append("```")
                for loc, content in hits[:20]:  # 最多列 20 处
                    lines.append(f"{loc}  {content[:100]}")
                if count > 20:
                    lines.append(f"... 还有 {count - 20} 处")
                lines.append("```")
                lines.append("")

    # Refactor task 建议清单
    lines.append("---")
    lines.append("")
    lines.append("## Refactor task 建议清单(协调端审 → 决定派 task / 忽略)")
    lines.append("")
    all_results = []
    for platform, results in [("Android", android_results), ("iOS", ios_results)]:
        for rule_id, (rule, hits) in results.items():
            count = len(hits)
            if count > 0:
                _, desc, _, _, severity, _, _ = rule
                all_results.append((platform, rule_id, desc, severity, count))

    all_results.sort(key=lambda x: (-{"high": 3, "medium": 2, "low": 1}[x[3]], -x[4]))

    if not all_results:
        lines.append("无 refactor 建议(全 0 命中)")
    else:
        lines.append("| 端 | 规则 | 严重度 | 命中数 | 建议 task |")
        lines.append("|---|---|---|---|---|")
        for platform, rule_id, desc, severity, count in all_results:
            task_hint = f"派 task 重构 (~{(count // 5 + 1)}h)" if count >= 5 or severity == "high" else "可暂留"
            lines.append(f"| {platform} | `{rule_id}` {desc[:30]} | {severity} | {count} | {task_hint} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 后续 action(协调端)")
    lines.append("")
    lines.append("1. 高严重度命中 → 立即派 task md(命中 ≥ 5 处的整改 + 加 grep lint 防复发)")
    lines.append("2. 中严重度命中 → 评估是否影响首版,影响则派 task,否则记 audit-log 待 sprint 处理")
    lines.append("3. 低严重度命中 → 可批量 issue tracking,新代码增量改善")
    lines.append("4. 0 命中规则 → 已守住,无 action")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 已知 false positive 模式(需 case-by-case 排除)")
    lines.append("")
    lines.append("- **`private val binding get() = _binding!!`** — Android Fragment ViewBinding 标准模式,不是反例(`kt-force-unwrap`)")
    lines.append("- **`val xxx: View = itemView.findViewById(...)`** — RecyclerView ViewHolder 标准模式,不是反例(`kt-findviewbyid`)")
    lines.append("- **`InfraXxx.shared`**(InfraNetwork / InfraStorage 等基础设施单例)— Infra 层合理 singleton(`sw-singleton-shared`)")
    lines.append("- **`NotificationCenter.default.post(name: .AppLanguageDidChange)`** — 跨 module 通信无更好替代(`sw-nc-post`)")
    lines.append("")
    lines.append("协调端审命中清单时,**先排除以上 FP 模式**,剩余真命中再决定派 task。后续 sprint 可在脚本加 FP 过滤逻辑。")

    return "\n".join(lines)


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    print("📋 扫描 iOS / Android...")
    ios_results = scan_platform("iOS", IOS, SWIFT_RULES) if IOS.exists() else {}
    android_results = scan_platform("Android", ANDROID, KOTLIN_RULES) if ANDROID.exists() else {}

    report = render_report(ios_results, android_results)

    if dry_run:
        print("\n" + report)
        return 0

    out_dir = PROJECT / ".ai-workspace"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"refactor-review-{date.today().isoformat()}.md"
    out_file.write_text(report, encoding="utf-8")
    print(f"\n✅ 报告已生成: {out_file}")

    # 打印摘要
    total_ios = sum(len(hits) for _, (_, hits) in ios_results.items())
    total_android = sum(len(hits) for _, (_, hits) in android_results.items())
    print(f"\n摘要:iOS {total_ios} 命中 / Android {total_android} 命中")
    return 0


if __name__ == "__main__":
    sys.exit(main())
