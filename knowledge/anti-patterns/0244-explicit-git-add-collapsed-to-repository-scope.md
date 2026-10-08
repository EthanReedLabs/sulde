---
doc_id: "ap-0244"
container: anti-patterns
platform: none
summary: "监督器把带显式文件列表的 git add 折算成仓库根写入，迫使单文件任务申请不必要的全仓权限，并让未跟踪发布输入陷入 bootstrap 自锁。"
related: [ap-0075, ap-0192, ap-0243, work-model/git-worktree-content-evidence-materialization]
sedimentation_schema: 2
problem_type: host-inconsistency
evidence_status: verified
---

# 0244 — 精确 Git 暂存被压成仓库级权限

- **平台**：协调端方法论（Git index / Agent Hook / 发布制品）
- **复发次数**：2

## 问题原型

任务只需要把一个已经审阅的知识文档加入 Git index，使确定性索引器能够发现它。调用使用
`git add -- <明确文件>`，没有目录、通配符、交互选择或仓库范围选项。监督器却只识别
`git add` 这个动词，把写目标统一记成仓库根 `.`。路径契约因此无法表达“允许更新 index，
但只允许这几个工作树文件进入 index”，单文件任务只能在以下错误选项间二选一：申请全仓
写权限，或永远无法登记新文件。

同一缺陷会放大发布 bootstrap 风险。stager 可以显式消费尚未进入 index 的运行时模块，而
旧版守卫的安装摘要只覆盖 tracked 文件和一份旧的显式清单。若直接安装，新模块字节没有
进入批准摘要；若先暂存，旧守卫又要求仓库根权限。结果是安全门禁和安全发布互相等待。

## ❌ 错误

- 只按 Git 子命令分类，把所有 `git add` 的目标固定为 `.`。
- 因为 `.git/index` 是共享元数据，就把“index 会变化”等同于“工作树任意路径都获授权”。
- 允许 `git add -A`、`git add -u`、目录、glob、pathspec magic 或交互暂存共享单文件例外。
- 为完成 bootstrap，临时给共享 dirty worktree 开仓库根权限，依赖 Agent 自觉只执行一条命令。
- stager 消费未跟踪运行时文件，但 proposal digest 没有逐字节覆盖这些输入。

## 为什么错

Git index 是共享、串行化的元数据资源，但一次暂存动作同时具有两个不同维度：

1. **并发/事务维度**：任何 index 写都必须串行，避免 `index.lock` 冲突和跨终端交错；
2. **授权维度**：本次允许从工作树进入 index 的路径集合应等于命令中已经解析并验证的显式
   文件集合，而不是整个仓库。

把两个维度压成 `target="."`，既不能表达最小权限，也不能证明发布输入。Git 内部必然更新
`.git/index` 并不意味着调用者获得直接写 `.git/*` 的能力；它应被建模成“执行精确暂存动作
的受控后果”。反过来，只有当每个 pathspec 都能机械证明为现存普通文件时，才有资格使用这
个窄例外。

已验证的一手证据包括：

1. `_command_write_targets` 对普通 `git add` 固定返回 `.`；
2. 子路径契约对 `git add -- <该文件>` 返回越界拒绝，错误文案显示目标为仓库根；
3. 现有单测把 `git add -A` 在仓库根授权下可执行固化成期望；
4. 新知识文档因此无法进入 `git ls-files`，全量知识索引继续只看到旧文档数；
5. 两个新的运行时模块也尚未跟踪，而旧安装运行时的显式发布输入清单不含它们，直接重装会
   产生批准摘要与真实制品输入不一致。

## 适用边界

- 只适用于单条、无 shell 组合的 `git add -- <path>...`。
- 每个 operand 必须是显式 literal：不得以 `-` 或 `:` 起始，不得包含 glob 元字符，不得是
  `.`、`..`、目录、symlink、缺失路径或 `.git` / `.codex-agent` 控制路径。
- 文件必须解析到当前 Git 工作树内的普通文件；相对路径以命令的受信 cwd 为基准，`git -C`
  只有在其工作树也能精确解析并绑定时才可支持。
- `git add -A`、`--all`、`-u`、`--update`、`-p`、`--patch`、`-i`、`--interactive`、
  `--pathspec-from-file`、目录与任何 pathspec magic 不适用，继续作为仓库级/未知写入拒绝。
- `git commit`、`merge`、`reset`、`clean`、`push` 和直接 `.git/*` 写入不共享此例外。
- 共享 worktree 仍必须保证单写者和 index 串行化；精确路径授权不是并行 Git 写许可。

## 判定样本

### 路由正例

- **输入**：单文件沉淀已通过 lint，但 `git add -- knowledge/anti-patterns/NNNN-*.md` 被守卫
  折算为 `.` 并要求仓库根权限。
- **预期**：apply
- **原因**：调用显式列出一个 literal 文件，实际授权需求与监督器建模目标不一致。
- **来源**：observed

### 路由反例

- **输入**：`git add -A` 在共享 dirty worktree 中准备暂存所有变化。
- **预期**：skip
- **原因**：它没有有限、可枚举的工作树文件集合，必须保持仓库级高风险边界。
- **来源**：constructed

### 执行合格例

- **做法或输出**：词法层仅接受单条 `git add --`；文件系统层逐项证明现存普通文件、位于
  当前工作树且不命中控制路径；事件生成这些文件的结构化 `write_targets`。契约只授权其中
  某个文件时，额外 operand 会整体拒绝；命令完成后独立核对 index 只新增预期路径。
- **预期**：pass
- **原因**：index 写仍受监督和串行化，但没有把共享元数据误当成全仓内容权限。
- **来源**：constructed

### 执行失败例

- **做法或输出**：看到 `git add` 就返回命令后的字符串；或仅排除 `-A`，仍接受目录、
  `*.md`、`:(glob)`、symlink 和 `--pathspec-from-file`。
- **预期**：fail
- **原因**：这些形态不能证明最终进入 index 的有限文件集合，仍可扩大到未审阅内容。
- **来源**：constructed

## ✅ 正确

1. 纯词法策略只识别唯一安全形状：无组合的 `git add --` 加一个或多个 literal operand；任何
   选项或特殊 pathspec 直接不返回精确目标。
2. 守卫以受信 cwd 解析每个 operand，要求 `lstat` 为普通文件、拒绝 symlink/目录/缺失路径，
   并证明解析结果位于当前工作树内且不穿过控制目录。
3. 事件携带结构化 `write_targets`，路径策略逐项匹配 allowed/frozen 范围；`.git/index` 变化
   只作为这次受控 Git 动作的内部后果，不产生通用 `.git` 权限。
4. 非精确形态继续落到 `.git` / unresolved 保护目标并拒绝；仓库根授权也不应自动放行
   `-A`、`-u`、目录或交互暂存。
5. 发布前的批准摘要必须覆盖 stager 实际消费的每个字节。若旧运行时不知道新显式输入，先把
   逻辑迁入旧摘要已经覆盖的 tracked/explicit 模块，发布新解析器后再精确登记新文件；不得用
   临时全仓权限跨过 bootstrap。

## 消费与防复发

- PreTool 命令规范化、路径契约、Git index 单写者和 release inventory 共同消费本规则。
- 单元测试同时覆盖 lexical 接受/拒绝矩阵和真实临时工作树中的文件/目录/symlink 边界。
- 集成测试必须断言 `write_targets` 是逐文件列表，并证明任一额外未授权 operand 会拒绝整个
  调用，而不是只检查首个目标。
- 发布测试比较 Guardian 摘要输入清单与 stager release inventory；集合或内容摘要不一致时
  fail closed。
- 真机 canary 只暂存本次新文档，随后用 `git diff --cached --name-only -- <明确文件>` 核对；
  不运行 `git add -A`，不提交，不清理共享 index。
