# G2 强类型 EffectRouter

## 范围结论

G2 新增 host-neutral 的 `sulde_effects` 能力注册表，并把它接入事件 effect 分类与
独立 verifier 匹配。已注册能力优先使用精确名称和强类型元数据；未注册能力继续走
显式 legacy fallback。Bash、Git、ApplyPatch 和本地文件目标解析仍由既有结构化解析器
负责，本轮没有改写 authority ledger，也没有引入第二个 writer。

## 已实现

- `CapabilitySpec` 冻结 canonical name、aliases、argument schema、effect class、最低
  authority、并行度、verifier、rollback 和 timeout policy。
- `EffectRouter` 在构建时拒绝重复 canonical name 和 alias collision，内部 registry
  使用只读 mapping；查找只接受规范化的 tool/skill/MCP capability identity。
- 已注册 Figma 读能力（含 `download_assets`）固定为 `read/no_effect`，不会再因
  completion callback 缺失或动作名称不含 read 动词而升级为 effect debt。
- Figma 变更能力固定为 `external_write`，其 `intent` authority 表示必须绑定当前任务
  意图，不代表每次 MCP 调用都新增一轮人工确认。
- Sulde memory read/annotate 能力使用精确 verifier 列表。普通 `memory_annotate` 仍是
  共享持久存储的外部写；只有既有 sealed continuation profile 验证具体参数后，单次
  invocation 才可窄化为 host-local write。
- `intervention.verifier_matches` 对已注册 write capability 只接受注册表中的 exact
  verifier；旧文档类 capability 未注册时仍保留 suffix/verb 兼容匹配。

## 兼容与安全边界

- registry first 只替代有精确 capability identity 的 effect/verifier 语义，不覆盖
  shell/source/target 的深度解析。
- 未注册 MCP 的 read/write 动词推断保留为 `legacy_fallback`，无可证明语义仍为
  `unknown`。
- read spec 不能声明 write authority 或 effect timeout；destructive spec 只能声明
  human/deny，构造阶段即 fail-closed。
- CapabilitySpec 中的 authority 是 supervisor 后续判定的最低 authority 类型；本轮
  未让 metadata 自行签发权限，也未改变现有 task-level approval 规则。

## 验证结果

- EffectRouter + resource + intervention 定向：80/80 通过。
- 全部 `test_intent_guardian*.py`：194/194 通过。
- 首次扩大测试捕获 3 个 `memory_annotate` 兼容回归；收紧普通 capability 为
  `external_write`、保留 sealed invocation 的既有窄化门后全部关闭。
- `git diff --check` 通过。

## 发现与决策

- **FG2-001**：能力类型不能只由动作名中的动词决定。`download_assets` 是已知 read
  capability，但旧 inference 会在中断时形成虚假 effect debt。
- **FG2-002**：同一 capability 的默认 effect 与一个受约束 invocation 的窄化 effect
  必须分开。把 `memory_annotate` 全局标成本地写会绕过 provider/schema/budget 门。
- **FG2-003**：精确 verifier 只对已注册 write 生效；直接删除 legacy fallback 会让
  历史文档适配器失去兼容验证路径。
- **FG2-004**：EffectRouter 不应重复实现 shell、Git 或补丁 target parser；它负责
  capability policy，资源身份仍由现有 typed resource 层负责。

## 后续入口

- G3：bounded inbox + generation-fenced 单写者消费 G1 typed events，并引用 G2
  capability spec；Hook/CLI 退化为 producer。
- G4：旧 JSON/JSONL 只读适配与 reducer projection 对比；一致性通过前不切换真相源。
- G5：将 capability registry digest 纳入冻结的 TaskEpochContext，热更新仅作用于下一
  epoch。

## 沉淀候选

### 候选：能力默认语义与受约束调用窄化必须分层

#### 任务与意图

- **问题类型**：anti-pattern update
- **任务目标**：用 typed capability registry 替代不稳定的动作名推断，又不扩大权限。
- **用户真实预期**：只读工具中断不再锁死任务，真实写入仍保留严格证据债务。
- **触发场景**：同一 MCP capability 既有普通共享写，也有满足固定 schema/verifier 的
  受控本地 continuation。

#### 观测与证据

- **可观察症状**：注册表初版把普通 annotation 全局窄化为本地写，扩大测试出现 3 个
  allow/deny 与 effect 分类回归。
- **期望与实际差异**：期望只有 sealed invocation 窄化；实际 capability 默认值覆盖了
  invocation-level 门。
- **已确认根因**：把 capability 默认 effect 和具体调用 profile 的条件化 effect 合并。
- **已排除假设**：问题不是用户授权不足，也不是 MCP transport 本身决定权限。
- **证据状态**：verified
- **一手证据**：扩大测试首次 3 failures，修正后 194/194 与定向 80/80 通过。
- **正确做法及验证**：默认值保持较宽 effect；窄化必须绑定 schema、provider、budget、
  runtime/content digest 和独立 verifier。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 动作名不能表达真实 effect，且有稳定 capability identity | apply | registry 能消除 verb inference 漂移 | observed |
| 路由反例 | capability 的 effect 取决于未校验的任意参数 | skip | 不能全局静态窄化 | observed |
| 执行合格例 | 默认 external write，sealed invocation 经独立验证后窄化一次 | pass | 权限不扩大且减少重复人工确认 | constructed |
| 执行失败例 | 把整个 annotation capability 标为 local write | fail | 绕过共享存储与 provider 边界 | observed |

#### 上浮边界

- **建议处置**：并入更新既有“只读 MCP 中断误升级为 effect intervention”条目，补充
  invocation-level narrowing 反例，不新建重复主题。
- **必须删除或泛化**：具体服务器名、会话、任务号和仓库路径。
- **可跨项目复用的内核**：typed capability 给出安全默认值；参数驱动的降级必须由
  sealed profile 单独证明。
- **建议容器**：anti-patterns
- **候选消费者**：EffectRouter、approval policy、MCP adapter、recovery verifier。
