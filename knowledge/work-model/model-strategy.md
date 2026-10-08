---
doc_id: "work-model/model-strategy"
container: work-model
platform: none
summary: "任务只记录宿主无关能力档，目标 Claude Code 或 Codex 会话再按当前模型翻译为原生模型与推理控制。"
sedimentation_schema: 2
problem_type: host-inconsistency
evidence_status: verified
---

# 多宿主模型与推理档策略（唯一真值）

> 任务复杂度是跨宿主真值；模型 ID、slash command 和推理档属于目标宿主的瞬时状态。

## 问题原型

协调端需要把同一份任务交给不同 Agent 宿主执行。共享任务应稳定表达最低能力需求，但若直接
写入某个提供方的型号与命令，切换目标 session 后就会生成无效指令，甚至误降级当前模型。

## 根因与证据

根因是把稳定的任务复杂度与易变的宿主控制面混成同一契约，并用“机器安装了什么”代替目标
session 身份。双宿主回归、安装缓存 smoke 和禁止词断言已验证：先保存能力档、再按显式
provider 渲染，可以稳定隔离两端协议；仅修改自然语言示例不能封闭绕过路径。

## 适用边界

- 适用于共享 task、协调端派单、返修和继续任务时的模型/推理档选择。
- 单宿主内部且不会复用到另一宿主的临时说明，可以直接使用该宿主术语。
- provider 或当前档位不可观察时必须请求确认；不得凭本机 CLI、默认配置或历史会话猜测。

## 判定样本

### 路由正例

- **输入**：同一 task 可能由 Claude Code 或 Codex 执行，需要生成“给 Agent 发送”的档位前缀。
- **预期**：apply
- **原因**：任务能力与宿主控制需要在派单边界进行确定性翻译。
- **来源**：observed

### 路由反例

- **输入**：比较两个 Codex 模型的通用性能，不生成任务或会话控制指令。
- **预期**：skip
- **原因**：不存在共享任务契约和目标宿主派单边界。
- **来源**：constructed

### 执行合格例

- **做法或输出**：task 写 `capability_tier`，派单显式传 provider 与当前状态；当前档位达标则
  保留，否则只输出目标宿主原生选择方式，并通过安装态回归。
- **预期**：pass
- **原因**：既避免跨宿主泄漏，也避免无条件切换打断上下文。
- **来源**：observed

### 执行失败例

- **做法或输出**：根据电脑上存在 Claude CLI，就在 Codex 会话前追加 `/model opus`。
- **预期**：fail
- **原因**：安装事实不能证明目标 session，且命令不属于 Codex 控制协议。
- **来源**：observed

## 正确做法

以下规则把能力档作为领域真值，把模型与推理控制限制在显式 provider 的适配边界；所有自然
语言生产者必须通过同一稳定 launcher，不能手写前缀。

## 任务契约只写能力档

新 task 必须写 `capability_tier`，禁止把某个提供方的型号当成共享字段：

```yaml
assignee: as-a
branch: dev/as-a/feature-foo
capability_tier: balanced   # light | balanced | deep
```

| 能力档 | 典型任务 | 最低要求 |
|---|---|---|
| `deep` | 架构/跨模块重构、复杂状态机、隐藏异步根因、跨真值冲突、复发型问题 | 当前宿主的深度能力；Codex reasoning 至少 `high` |
| `balanced` | 已知复现的 bug、新 Feature、UI 还原、API 接入、中等改造 | 当前宿主的平衡能力；Codex reasoning 至少 `medium` |
| `light` | 明确的一行修复、字段/配置、翻译、资源、确定性编译错误 | 当前宿主的轻量能力；Codex reasoning 至少 `low` |

能力档是**最低线**。当前 session 已高于最低线时保留，不强制降档打断上下文；若要降本，
在下一项任务前由用户选择。

## 先识别目标 session，再翻译

协调端派单前必须拿到**目标执行 session**的三项事实：

1. `provider`: `claude` 或 `codex`；
2. 当前 model；
3. 当前 reasoning/thinking 状态（宿主可观察时）。

来源优先级：目标会话的宿主上下文/状态命令 > 用户明确说明 > 宿主配置默认值。
机器同时装了两种 CLI 不是当前宿主证据。宿主不明确时停止并要求显式选择，绝不静默借用另一端。

确定性参考实现：

```bash
python3 scripts/kb/model-dispatch.py \
  --provider codex \
  --tier deep \
  --current-model <当前 Codex model> \
  --current-tier deep \
  --current-effort high \
  --task .ai-workspace/tasks/<task>.md
```

## Claude Code 渲染

Claude Code 可把能力档映射为其原生模型族，并用 Claude 原生 `/model`：

| 能力档 | Claude 模型族 | thinking 提示 |
|---|---|---|
| `deep` | `opus` | `ultrathink` |
| `balanced` | `sonnet` | `think hard` |
| `light` | `haiku` | 默认/`think` |

示例：

```text
/clear
/model opus
/assign 任务文件:.ai-workspace/tasks/<task>.md
```

这张映射只在 Claude 适配层存在；`opus/sonnet/haiku` 不得回写成新 task 的公共真值。

## Codex 渲染

Codex 的模型选择与推理强度是两个维度：

| 能力档 | 当前默认 Codex 模型 | reasoning 最低线 |
|---|---|---|
| `deep` | `gpt-5.6-sol` | `high` |
| `balanced` | `gpt-5.6-terra` | `medium` |
| `light` | `gpt-5.6-luna` | `low` |

`xhigh` 与 `max` 是 reasoning 档，不是模型名。目标账号没有表中精确型号时，从该 Codex
会话的 `/model` 可用列表选择同能力档或更高型号；不得退回 Claude 型号。

- 当前模型能力档满足任务要求：保留当前模型；
- 当前模型不足或未知：使用 Codex 原生 `/model` 打开可用列表，选择表中型号或同档以上；
- reasoning 低于最低线或未知：使用 `/reasoning` 打开选择器，选择最低线或更高；
- 最后直接要求当前 Codex session 执行 task 文件，不输出 Claude `/assign`。

示例（当前 Codex 模型与 reasoning 已满足）：

```text
当前模型与推理档位已满足任务要求，无需切换。
执行任务文件:.ai-workspace/tasks/<task>.md
```

示例（当前 Codex session 不足）：

```text
/model
选择:当前 Codex 可用列表中的 deep 档模型
/reasoning
选择:high 或更高
执行任务文件:.ai-workspace/tasks/<task>.md
```

Codex 路径禁止出现 `/mode`、`/model opus`、`/model sonnet`、`/model haiku`。
协调端必须通过 `$dispatch-task` 调稳定 `model-dispatch` launcher 并原样粘贴 stdout；禁止
手写“给 Dev 发送”的模型/推理前缀。

## 旧 task 兼容

归档 task 中的旧字段可以在**读取时**迁移：

| 旧字段 | 内存映射 |
|---|---|
| `model: opus` / `thinking_mode: ultrathink` | `deep` |
| `model: sonnet` / `thinking_mode: think-hard` | `balanced` |
| `model: haiku` / `thinking_mode: think` | `light` |

若两个旧字段冲突，取更高能力档并报警。兼容器不得修改归档，也不得让新 task 继续写旧字段。

## 验收不变量

- 新 task 有 `capability_tier`，没有提供方特定 `model`/`thinking_mode` 字段；
- 派单生成器先看目标 session，不从“机器装了什么”猜当前宿主；
- Claude 输出只含 Claude 原生控制，Codex 输出只含 Codex 原生控制；
- 当前模型高于任务最低线时允许复用，不强制降档；
- 宿主或当前状态不明确时显式提示，不生成跨宿主命令；
- 归档兼容仅发生在读取边界，新写路径保持干净。

## 消费与防复发

- `dispatch-task` Skill、协调端任务模板和 `model-dispatch` launcher 共同消费本策略。
- schema 测试拒绝新任务中的提供方字段；双宿主输出测试机械拒绝对方模型名与控制词。
- 发布验收必须从真实安装缓存调用 launcher；目标 session 不明确仍需人工确认。

## 关联

- `skills/coordinator/writing-task-md/SKILL.md`：协调端能力档选择与派单格式；
- `skills/dev/assign/SKILL.md`：接单端宿主识别与兼容边界；
- `scripts/kb/runtime_provider.py`：确定性映射和渲染实现；
- `docs/dual-runtime-contract.md`：不静默跨提供方回退的运行契约。
