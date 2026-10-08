---
doc_id: "ap-0203"
container: anti-patterns
platform: none
summary: "set -e/pipefail 脚本里 grep/rg 计数或过滤,零匹配时脚本静默退出或把正常空结果当失败处理"
related: [ap-0195, ap-0204, tech-docs/docker-platform-export-verification]
sedimented_by: auto
---

# NNNN — set -euo pipefail 下 grep/rg 零匹配返回码 1 被误判为失败

- **平台**:none

## ❌ 错误

在 `set -euo pipefail` 的脚本里直接用 `grep` / `rg` 做计数、过滤或存在性检查(如 `count=$(grep -c pattern file)`、`hits=$(rg pattern | wc -l)` 中的 grep 段),默认零匹配是合法业务场景。实际上 grep/rg 约定**无匹配时退出码为 1**,`set -e`(或管道中 `pipefail`)会把这个 1 当作命令失败:脚本在本该继续的地方静默中止,或错误分支被触发——正常的"零匹配"被误判为"执行失败"。

## 为什么

- grep 家族的退出码是三态语义:0=有匹配,1=**无匹配(正常)**,≥2=真错误。`set -e` 只看非零,无法区分"没找到"和"跑挂了"
- 零匹配往往是最常见的合法路径(检查违规项、统计新增条目、扫描候选),恰恰是这条路径触发退出
- 失败是静默的:脚本中途退出不留痕迹,或 `$(...)` 捕获链断裂,调试时症状(脚本"跑一半没了")与根因(退出码语义)相距很远

## ✅ 正确

- 计数/过滤类调用一律 no-match-safe 写法:`grep -c pattern file || true`、`hits=$(rg pattern || true)`,或 `grep pattern file; rc=$?; [ $rc -le 1 ] || exit $rc` 显式区分真错误
- 存在性判断用 `if grep -q pattern file; then ...` 结构(`if` 上下文中非零退出码不触发 `set -e`)
- code review / 自检时,凡 `set -e` 脚本里出现裸 grep/rg 于赋值或管道中,默认怀疑零匹配路径未覆盖,补 `|| true` 或显式 rc 处理

## lint

可半机械化:在 `set -e` 脚本中 grep 形如 `\$\((grep|rg) ` 且同行无 `\|\| true` / `-q` 的调用点,人工确认零匹配是否为合法场景。
