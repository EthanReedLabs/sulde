# T32 Codex worktree Git 归因与历史验收迁移

## 范围结论

T32 保持为一个任务，没有拆分 successor。产品改动由 `6c3ef24` 与
`8881570` 组成，`60995fc` 只更新官方 Codex cachebuster；`c7fd29a`
把一个未登记的重复测试恢复到冻结基线，因此最终产品净差异严格落在登记的
七个源码/测试/manifest 路径内。T31 的 seq338–341 记录是先行任务的控制证据，
不计入 T32 产品 owned paths。

## 已解决问题

### F32-001：Codex linked worktree Git 写入归因错误

- 旧逻辑在主工作区收到 `git -C <linked-worktree> ...` 时会退化到主仓库或
  `.git` 元数据目标，导致已授权 worktree 文件仍被拒绝。
- 新逻辑只接受可证明属于当前 workspace 的真实 worktree。linked `.git`
  指针、反向 `gitdir`、管理目录归属、路径组件和 symlink 都必须一致。
- `git add -- <literal files>` 逐文件归因；安全 `commit` 和安全 `merge`
  归因到实际 worktree 根。`-A`、路径越界、别名、外部仓库、`--amend`、
  自定义 merge strategy 和控制路径继续 fail closed。
- 安装后真实 canary 已用 T31 worktree 完成精确 add、commit，并用
  `git -C ... merge --no-ff --no-edit` 完成 dev 合并；随后 main 只做 ff-only。
  一次带 `merge -m` 的未覆盖语法被 PreToolUse 正确拒绝且仓库无状态变化。

### F32-002：native 决策卡嵌套展示文案触发别名冲突

- 根因是机器展示别名递归扫描整张卡，嵌套续行动作中的自然语言 `动作` 被误当成
  顶层规范决策字段。
- 修复后只在卡片顶层读取展示别名；顶层动作被篡改仍拒绝，嵌套续行说明可共存。

### F32-003：拆分后资源模块仍超过组件预算

- 首次官方 full-clone gate 发现 `resources.py` 仍超过 3000 行。
- 把文件操作 helper 移入已有 `local_file_operations.py`，依赖方向保持单向，
  `resources.py` 收敛到 2991 行；未新建职责重叠模块。

### F32-004：安装 grant 被 Git index 身份变化失效

- cachebuster helper 后先提交 manifest 会改变 `git ls-files --stage` 中的 blob
  身份，即使工作树字节不变，已密封 installer grant 也必须失效。
- 未绕过校验；在当前已提交树上重新生成一次性 installer grant 后再执行官方安装。
  后续流程应先完成最终 release commit，再密封并执行安装 grant。

### F32-005：T32 任务定义漏列重复测试路径

- 登记后核对 `f019ee9..60995fc` 发现 `tests/test_command_policy.py` 只有一个
  import 和一个重复 parser assertion，却不在 owned paths。
- 任务进入 blocked；`c7fd29a` 把这五行恢复到基线。263/263 相关测试仍通过，
  最终净差异不再包含该路径，且安装制品从未包含仓库测试文件。

## 验证结果

- scoped：263/263 通过，覆盖 command policy/template、Guardian resources/state、
  native decision journal 和 local file operations。
- official full clone：1370/1370 通过，6 个平台 skip，耗时 301.396 秒；使用空的
  production sentinel，没有生产 KB 写入。该候选包含最终产品字节；后续
  `c7fd29a` 只删除一个制品外重复测试。
- dev/main：T32 源码与 cachebuster 先进入 dev/main；T31 canonical evidence
  随后经 dev merge 和 main ff-only 合入。产品 runtime 字节没有在安装后改变。
- install：官方事务安装器提交
  `0.2.5+codex.20260824145354-ce28ce210c:51871da47829fc47ec66978207d40e44c4c2df99580c266826753f2c19b52484`。
- scheduler：官方 reconciliation 后 15 managed / 15 loaded，failed 与 missing
  均为空，runtime owner active。
- live host：当前 Codex session 的 prompt/session 通过 verified hot rebind，
  当前 runtime 的 PreToolUse/PostToolUse 与 PermissionRequest 均 live verified；
  operational readiness 为 ready，effect debt clear，decision pairing settled。

`deployment_status` 字段仍保留 installer 的 `installed_live_unverified` 阶段标签，
但 artifact、scheduler、interactive、effect 与 pairing 五个独立域均由当前观测判定
为 ready；本报告不把阶段标签改写为不存在的值。

## 历史需求迁移审计

没有重放或改写旧事件。只迁移以下已经独立核验的事实：

- 旧完成链来自 stash untracked commit `ef81f9c0`，共 1158 条事件；逐条 sequence、
  previous hash 和 event digest 全部有效，seq1158 为 `program_completed`。
- 当前链与旧链共同前缀到 seq101，公共 head 为
  `57ecfa0b9e59fa65c2d10732276e553499da02a862d5ab04ca217925b9387a1c`；
  两者从 seq102 分叉，因此不存在把旧 seq102 以后事件直接追加到当前链的权限。
- 旧 requirement evidence 的文件 SHA-256 与 seq1100–1103 登记值逐项一致：
  T10/WP56-E、T13/DERIVED-TIMEOUT、T18/DERIVED-CRITIC 与 DERIVED-SPLIT、
  T37/WP56-B。
- 对应任务分别在 seq388、680、583、1099 accepted；旧链最终完成。
- 组合提交 `ebd9c2e` 把 accepted seq819 基线落入 Git，`d8169a2` 落入 T37
  最终闭环；两者均为当前 HEAD 祖先。当前 1370 项系统 gate 又覆盖了这些代码。
- WP56-D 不从旧链迁移，改由本次安装后的真实 worktree add/commit/merge canary
  直接证明。

## 沉淀候选

### 候选一：安全 Git 语法必须同时建模内容授权与元数据后果

#### 任务与意图

- **问题类型**：host-inconsistency
- **任务目标**：让受控 linked worktree 的精确 Git 写入不再被主仓库元数据误阻断。
- **用户真实预期**：正常 Git 工作流不需要为内部 `.git` 后果反复申请全仓权限。
- **触发场景**：监督器从主 workspace 观察 `git -C <linked-worktree>`。

#### 观测与证据

- **可观察症状**：精确 add/commit/merge 被归为错误的 `.git` 目标。
- **期望与实际差异**：内容目标和内部元数据后果被压成同一个授权目标。
- **已确认根因**：缺少 linked pointer 双向校验及子命令安全语法模型。
- **已排除假设**：不是人工 Allow 失效；PreToolUse 在执行前已确定性拒绝。
- **证据状态**：verified
- **一手证据**：263 项 scoped、1370 项 full clone、安装后 add/commit/merge canary。
- **正确做法及验证**：逐文件归因 add，repository-scope 归因安全 commit/merge，
  未证明语法继续落入 `.git` fail closed。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | `git -C <受控 worktree> add -- one.md` 被归到主仓库 `.git` | apply | worktree 和 literal 文件均可机械证明 | observed |
| 路由反例 | `git add -A` 要求仓库级写入 | skip | 内容集合不可枚举 | constructed |
| 执行合格例 | pointer/reverse pointer 一致，事件目标为真实文件或 worktree 根 | pass | 内容授权与元数据后果分离 | observed |
| 执行失败例 | 为通过 merge 临时允许任意 `.git/**` | fail | 扩大为不可审计元数据写权限 | constructed |

#### 上浮边界

- **必须删除或泛化**：本机路径、分支名、commit 和 session id。
- **可跨项目复用的内核**：Git 子命令安全语法与实际 worktree 身份必须共同决定授权目标。
- **建议容器**：anti-patterns
- **候选消费者**：Hook 监督器、命令策略测试、review checklist。

### 候选二：密封发布授权必须发生在最终 index 身份之后

#### 任务与意图

- **问题类型**：workflow
- **任务目标**：让一次性 installer grant 精确覆盖实际发布输入。
- **用户真实预期**：批准一次发布后不会因无字节变化的提交顺序反复授权。
- **触发场景**：grant 摘要包含 `git ls-files --stage` 元数据。

#### 观测与证据

- **可观察症状**：cachebuster 字节未变，但提交后旧安装 grant 被拒绝。
- **期望与实际差异**：工作树内容相同，index blob identity 已改变。
- **已确认根因**：先密封 grant、后提交 release metadata 的顺序错误。
- **已排除假设**：不是 installer 或 native PermissionRequest 随机失败。
- **证据状态**：verified
- **一手证据**：旧 grant 在任何安装状态变化前被摘要校验拒绝；重新密封后安装成功。
- **正确做法及验证**：完成最终 release commit 后再生成 grant，并在该树上立即执行。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | install grant 在 release commit 前生成 | apply | 后续 index 身份必然改变 | observed |
| 路由反例 | grant 只覆盖不可变 artifact digest 且 artifact 未变化 | skip | 没有 index 绑定 | constructed |
| 执行合格例 | final commit → seal → install → independent readback | pass | 同一输入身份贯穿事务 | observed |
| 执行失败例 | 校验失败后复用旧 receipt 或忽略 index metadata | fail | 绕过一次性授权绑定 | constructed |

#### 上浮边界

- **必须删除或泛化**：版本、commit、路径和 grant id。
- **可跨项目复用的内核**：密封授权必须位于最后一次会改变其摘要输入的操作之后。
- **建议容器**：work-model
- **候选消费者**：release Skill、installer、CI gate、review checklist。

## 未做事项

- 未修改、删除或重放生产 active contract、events/effect ledger。
- 未生成第二个 T32 任务，未重建计划，未切换到其他 provider。
- 未删除旧 stash、历史 worktree 或临时 full clone；清理不属于本任务验收。
