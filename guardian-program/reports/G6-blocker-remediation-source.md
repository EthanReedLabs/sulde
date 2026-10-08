# G6 发布阻断项源码修复

## 结论

G6 revision 6 的本地源码阶段已完成，精确源码提交为
`620e71aa19df1b11806c9a74f06e115df7fe322d`，父提交为
`3ee9e66ff0a9b6b0ab92e64df5ef0ed3e8d1eb4b`。

本阶段只关闭两个源码阻断项：

1. launcher-only refresh 不再全量覆盖一个仍然有效的 scheduler seal；只有
   deployment、runtime owner、generation、runtime root、provider/platform 与实际 runner
   字节全部一致时，才把 scheduler 扩展组合进新 launcher manifest。
2. 精确匹配旧版 `unsealed + prepared + no operation` 的 native row 仍完整保留在历史
   JSONL 和 cut source fingerprint 中，但投影为只读历史诊断，不再冒充可恢复/可执行的
   pending authority；sealed、未知或不完整 active row 仍然 fail-closed。

没有生成 cachebuster，没有安装插件，没有修改生产账本或 installed cache，没有重载
scheduler，也没有 merge 或 push。G6 仍需单独的部署 revision 才能继续。

## 修改范围

- `scripts/kb/launcher_contract.py`
- `scripts/kb/bootstrap.sh`
- `scripts/kb/native_decision_journal.py`
- `scripts/kb/sulde_projection/{models,legacy_adapter,cutover}.py`
- `tests/test_launcher_contract.py`
- `tests/test_sulde_projection.py`

legacy cut、semantic projection 与 cutover binding 的 schema 同步升级到 v2，避免在 v1
envelope 下静默增加新的诊断字段和改变 blocker 语义。

## 验证证据

### 红转绿

实现前四项新回归产生 1 failure、2 errors，准确复现 scheduler extension 丢失、历史行被
计入 pending 和诊断字段不存在。实现后 4/4 通过；runner 字节漂移、generation 漂移、
sealed row 和不完整 row 均继续拒绝继承或继续阻断。

### 定向与影响面

- launcher contract：25/25。
- Sulde projection：9/9。
- native decision journal：64/64。
- dual runtime + Windows bootstrap：22 通过、1 skip。
- operational readiness + P0 transaction integration：31/31。
- Codex transactional installer：39/39；隔离 clone 具有真实 Git metadata。
- Intent Guardian 全量：194/194；使用发布固定 Sulde venv。
- 官方 clean-clone discovery：1441/1441，6 skip，exit 0。
- `git diff --check` 与 staged diff check：通过。

全量数量比旧 G6 基线 1437 增加 4，来自本次新增的两个 launcher 测试与两个 projection
测试。

### 生产只读 cut

用本提交源码对主 Sulde contract 形成七源 optimistic read-only cut：

- cut：`e72978ab288f149e70ccd3e86795e132b8e6e97b93bc4d9172e9750f78f5ca20`
- sources：7/7。
- `pending_native_transactions=0`。
- `historical_unsealed_native_transactions=5`。
- blockers：0。
- schema：`sulde-legacy-control-cut-v2`。

collector 在读取前后对七个 source fingerprint 做 CAS 比较；单元回归另外逐字节断言 legacy
native JSONL 在 cut 前后完全相同。没有追加 supersede、seal、Allow 或 terminal row。

## Finding 处置

| Finding | 处置 | 证据 |
|---|---|---|
| FG6R-001 launcher writer 覆盖 scheduler extension | `fixed_source` | 双描述符 + runner byte seal 组合回归 |
| FG6R-002 legacy unsealed prepared 被当作 pending authority | `fixed_source` | v2 诊断投影、生产只读 cut 与 JSONL byte equality |
| FG6R-003 r5 external-write phase 禁止了本地源码写入 | `fixed_control` | 未落盘；r6 将源码和部署拆成独立 authority epoch |
| FG6R-004 测试 worktree 的 Hook 生成 bytecode 干扰完整树摘要 | `contained` | no-bytecode 的真实 Git clean clone；未放宽 runtime digest |
| FG6R-005 从 worktree clone 缺少 `origin/main` | `contained` | 改用仓库根 clone，确认 main/dev/feature refs 后全量通过 |

## 剩余发布条件

1. 新部署 revision 明确授权唯一 cachebuster、精确提交的官方事务安装和 scheduler/live
   验证；本源码 revision 不携带这些权限。
2. 安装后实际运行 launcher-only refresh/bytecode repair 场景，证明 15/15 jobs 持续 ready。
3. 使用 installed v2 投影重新读取生产 cut，确认历史 JSONL 不变且 blocker 保持为零。
4. Codex 旧/新会话 live 通过。
5. 真实 Claude 宿主可用时完成 live；不能用 synthetic 或 Codex 观察替代。
6. 所有 gate 同时通过后，才允许 task → `dev` → 集成验证 → `main`。

## 沉淀候选

### 权限合同按副作用阶段拆分

- **问题语境**：同一计划同时包含本地源码修改和未来生产安装。
- **证据状态**：verified。
- **正确样本**：本地实现使用 reversible local-write epoch；测试通过后另建 external-write
  部署 epoch。
- **失败样本**：把整批标成 external-write，导致 local-write=false，测试补丁被守卫拒绝。
- **建议路由**：control-plane workflow / phased authority。

### 全量测试 clone 必须同时具备干净字节与完整 refs

- **问题语境**：完整套件既校验 immutable runtime tree，也依赖 `origin/main`。
- **证据状态**：verified。
- **正确样本**：从仓库根 clone，确认 main/dev/feature refs，再覆盖当前 scoped diff，并设置
  no-bytecode。
- **失败样本**：rsync 副本没有 Git metadata；从 worktree clone 只有当前 branch remote ref。
- **建议路由**：test harness / release isolation。
