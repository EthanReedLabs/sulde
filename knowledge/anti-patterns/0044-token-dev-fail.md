---
doc_id: "ap-0044"
container: anti-patterns
platform: none
summary: "0044 协调端写技术文档/任务书时凭印象编\"项目实际状态\"(类名 / 文件名 / token 名 / 方法签名)→…"
---

# 0044 协调端写技术文档/任务书时凭印象编"项目实际状态"(类名 / 文件名 / token 名 / 方法签名)→ Dev 抄错引发编译 fail

- **平台**:协调端(写文档类)
- **复发次数**:多次(习惯性失误)

## ❌ 错误现象

| 实例类型 | 协调端写的 | 项目真实状态 |
|---|---|---|
| 设计模式举例 | "项目实际应用举例" 列某 Adapter 类 | 实际目录只有 base 类 + Mock 类,**无该 Adapter** |
| 编码原则 | 列某 UI 框架为首选 | 项目 grep 0 命中,基础设施未建 |
| token 引用 | 主题代码用 `AppColors.brand` / `AppColors.bgSurface` | 实际是 `object Colors { val primary = ... }`,token 名/类型都不同 |

**为什么错**:
- 协调端写"项目实际应用举例"/"现有 token"/"已有架构"等内容时,**易凭印象 / 凭跨平台经验编**
- Dev 严格按 task md 跑,抄错就**编译 fail**(`AppColors.brand 找不到`)或**架构错位**
- 反复踩坑表明这是协调端**习惯性失误**,不是单次问题

**协调端凭印象易错的内容类型**:
1. **类名 / 对象名**:`AppColors` vs `Colors`,引用了实际不存在的 Adapter
2. **token 名 / 字段名**:`brand` vs `primary`,`bgSurface` vs `background`
3. **方法签名 / 返回类型**:`AppTypography.material` vs 实际无此 property
4. **架构现状**:某 UI 框架是否引入 / lint 数 / scaffold 是否建好 / mock URL 是真 placeholder 还是占位
5. **文件路径**:`Sources/.../RealAdapter` vs 实际不存在
6. **依赖版本兼容**:编译器版本 vs 语言版本,某库 vs 协程

## 为什么错(根因)

- 协调端凭印象易错是**人性弱点**(跨平台 / 跨项目经验混淆)
- Dev 严格按 task md 跑,**契约错** = Dev 实施错(等 build fail / 用户验收"不对")
- handoff 客观证据规则是 **Dev 写 handoff 必含客观证据**;本条是**协调端写 task md 必先 grep verify**(对偶规则,共同闭环)

## ✅ 正确 — 写 task md / shared-rules / 编码原则集 等技术文档前必 grep verify

### a. 写"项目实际应用举例"前

```bash
# 类名 / 文件名 grep:
find <project> -name "AppColors*" -o -name "<某 Adapter>*"  # 确认存在

# 对象 / token 名:
grep -E "^\s*(val|object|class)\s+\w+" <design>/Colors.kt

# 方法签名:
grep -E "fun\s+\w+\(" path/to/file.kt
```

### b. 写"代码示例"前

每个引用的类名 / token 名 / 方法名都要 grep 真实存在。**不确定时**:
- 写"Dev 调研后决定"(给 Dev 调研步骤)
- 或写"按项目实际 [文件路径] 真实 token 填"(让 Dev grep)
- 或在 task md 内**直接附 grep 命令**,Dev 跑后用真实 token

### c. 写"架构现状"前(框架引入 / lint 数 / mock URL)

```bash
grep <注解> <project>/feature-*/src/main → 0/N 命中
ls <project>/scripts/lint/rules/ | wc -l
grep -r "https://" <project>/.../mock/
```

### d. 不确定时**写 todo 不写错**

```markdown
> Dev 实施前先 grep verify 以下信息:
> - <design>/Colors.kt 实际 token 名(我们的主题应 reference 真实 token,不要抄本 task md 里的占位名)
```

**不要写"假定 ... 内有 X"**(fallback 反例延伸)。

## How to apply

1. **协调端写 task md / shared-rules / 编码原则集 时**,涉及代码示例 / 类名 / token 名 / 现状描述:必先 grep / Read 验证真实文件;不确定 → 写 todo 让 Dev 调研,不写假名
2. **协调端 self-review 时检查命中**:文档内每个 `ClassName` / `methodName` / `tokenName` 是否真存在?文档内"项目当前 X"是否真 grep 验证过?不确定的内容是否标注让 Dev 调研?
3. **协调端工作流加这一步**(写技术文档前):写代码示例 → 先 Read 真实文件;列项目状态 → 先 grep / 跑命令;写 stat 数字(lint 数 / 命中数 / 文件数)→ 先实测

## 判定线

任务书 / shared-rules / 编码原则集 内含 grep 可验证的具体信息(类名 / 文件名 / token 名 / 现状数字),**协调端必先 grep verify**;凭印象写 = 违规。

## lint 状态

- 协调端写文档类,无静态扫描 → self-review checklist + 写文档前 grep/Read 真实文件
