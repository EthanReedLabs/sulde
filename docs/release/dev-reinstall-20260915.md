# dev 官方重新安装记录

## 范围与结论

- 请求日期 2026-09-15，实际安装与验收日期 2026-09-16（Asia/Shanghai）。
- 基线：已推送的 dev `4b1b891bda1339eefc54f515e65deacae10f0379`。
- 安装源码：`847b20f0808aa58c68fa1bd0acd1f99068df66b5`，已先快进合入 dev。
- 新版本：`0.2.5+codex.20260916020234-95d26eff5a`。
- 使用 plugin-creator 的官方 cachebuster helper 和 Guardian 的一次性安装授权，未手改安装缓存。
- 唯一非报告源码差异为插件 manifest 的 version 一行；运行源码没有变化。
- 不合 main、不自动 push，不修改其他项目、秘密、历史账本或知识库内容。

## 授权与执行证据

- 同一 Codex 会话：`01a00d6f-65b3-7663-b51b-f88684ffa561`。
- workspace handoff 先成功，然后重新生成同范围安装提案；未把旧工作区的批准转移为安装权限。
- 安装提案：`5421f342739df8e8a7fe1517a925f48256e74157c890f25c65cee6eb051a347d`，r3。
- 原生批准回执：`c617906ce2e4a8049012990fecec4b2f3bb011cb3c55a8ff42ecca44b7cc5e3f`。
- 原生事务：`ndt-66c0633f2acd2d41067d27a8e63d1b16`，applied。
- manifest 校验及 `git diff --check` 通过，版本变更提交后才准备候选。
- 唯一候选：`dev-reinstall-20260915-4b1b891`，prepare → verify → promote 成功，
  `status=promoted`、`promotion_consumed=true`；未重复安装。
- 候选验收回执：`37d5117318372b788236070972da68a2c2c7a3ddac2ac1dcecdd05b3e340916c`。
- 持久证据目录：`/Users/eric/.sulde/candidates/codex/dev-reinstall-20260915-4b1b891/`。
  `state.json` 包含安装终态，`verification-receipt.json` 包含安装前验证。
- prepare 2.292 秒、verify 19.333 秒、promote 48.646 秒；不含人工确认等待与前后检查。

## 安装前验证

- plugin manifest 与 marketplace 标识校验通过。
- 隔离真实 Codex 工具链通过：正向工具执行、破坏性 canary 在 PreToolUse 被拒绝、无外部模型请求。
- MCP initialize、Hook 入口、调度生产入口隔离 dry-run 通过。
- 隔离环境没有当前会话原生确认 UI，也不加载生产调度；这两项不冒充 live 验证。

## 安装后独立验收

- 缓存 manifest 独立读回版本正确，homepage/repository 均为
  `https://github.com/EthanReedLabs/sulde-pro`。
- 安装路径：`/Users/eric/.codex/plugins/cache/sulde-local/sulde/0.2.5+codex.20260916020234-95d26eff5a`。
- runtime tree SHA256：`0d41cb8faf06656774328b4b2681e7bf4d003a9d484d500a5efca0cb292b96d7`，
  与安装前旧版本相同，未增加运行逻辑改动。
- 六个稳定 launcher 均 healthy，指向新缓存；调度 seal verified。
- 本会话 doctor：status/interactive/operational 均 ready；效果债务 clear，
  pending verification=0、blocking=0、open intervention=0。
- 原生决策配对 settled=true、unsettled=0、CAS mismatch=0；没有未决审批需要再次弹窗。
- 实测 16/16 原有调度 labels loaded，missing/failed 为空，generation 一致。
  仅证明当前装载与配置健康，不声称所有周期业务已重新运行成功。
- 新 generation 的 tool_guard/tool_result 已被当前会话 live 观察到；
  prompt/session context 通过 verified workspace/runtime continuity 续接。
- 当前会话独立负向 canary `935630526d96b62afda48400fd364c67` 在执行前被真实 Hook 拒绝，
  official finalize 验证成功：proof `4bf2d17186f845a21fd36c6369efee6c37d920f1c9d08275f3e452b79ca85244`，
  `proof_current_generation=true`、`gaps_cleared=0`，未删除或豁免任何历史缺口。
- 安装器初始输出 live_host_unverified；以上是其后的独立 live 检查，不混淆两者。
- Skills 内容没有变化；当前 Hook 已热续接。宿主 skills catalog 仍可能保留旧路径，
  如需刷新目录应恢复同一线程；不以新开线程作为本次已通过 Hook 验收的前置条件。
- 当前长期 MCP 连接未被强行重启，不把安装链 MCP initialize 当作该连接切换的证明。

## 过程问题与范围控制

- 安装前对目标工作区发起原生批准被拒：目标尚非当前映射。随后先完成官方
  workspace handoff，再因 base policy 已变化重建同范围提案。拒绝发生在安装前，没有消费安装。
- 一次 handoff 预览误用 allow，合法语义为 approve；无状态变更，读回协议后纠正。
- 管理目录写入受宿主沙箱限制，均走原生提权；没有改路径规避、编辑账本或关闭守卫。
- 本次不修复/扩展 Guardian，不新增工作流；候选原始证据保留在任务 worktree 外。

## 收尾证据位置

报告提交并合入 dev 后，按 Guardian 正常完成接口释放本临时 worktree，再执行 Git 清理。
最终 cleanup 回执由 `release-completed-workspace` / `finalize-workspace-cleanup` 生成于
`/Users/eric/.sulde/data/kb/intent/sessions/`，不通过修改本报告预先声称清理成功。
