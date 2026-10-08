# 原生测试路径与可写边界定向修复

capability_tier: balanced

## 冻结范围

承接 [诊断报告](native-failure-diagnosis-20260923.md)。在同一任务分支
`task/native-failure-diagnosis-20260923`、dev 基线
`f5cbf6cde41c35ffb652a360c2f558a66e1c0c4c` 上实施；当前会话原生 Allow 已应用 revision 18。
只修隔离命令入口、原生候选 canary 和相应回归。原始诊断、失败日志和摘要保留。
不改变 Guardian 授权规则、生产安装、主分支、调度、正式知识库或图谱；不推送、不合并。

验收：路径别名与符号链接不能逃过拒写；候选账本、明确任务 worktree 可以写；未声明
兄弟目录不能写；真实 Hook 拒绝之后普通写入正常；默认临时根与迁址根结果一致。
使用真实 CLI / unified_exec / 候选 Hook 与独立回读，本地回环模型桩，不调用付费模型。

## 修改内容

1. `scripts/kb/run-isolated-tests.py`：公共 OS 命令构造入口规范化物理路径。
   不再依赖 main 或每个调用者先 resolve；预检仍将真实写入视为硬失败。
2. `scripts/release/native_pretool_canary.py`：workspace-write 候选显式配置账本、私有临时
   目录及调用方列明的工作树；拒绝非目录、候选外路径以及整个 isolated/Sulde home。
   关闭隐式 `/tmp` 和 TMPDIR 写权限，再显式列入候选私有 TMPDIR；网络权限不扩大。
   对 `thread/start` 返回策略逐项核验。宿主可能省略隐含的 cwd，比较时只补回该精确目录，
   不容忍缺失其他根、增加其他根或布尔策略漂移。
3. `tests/test_native_session_continuity.py`：显式列明源/目标工作树，不把 Guardian handoff
   等同于 executor 权限转移。普通续接和历史工作树释放仍运行原有强断言。
4. `tests/test_native_control_composition.py`：原有组合正反例之外，真实执行两次 touch，
   验证未声明兄弟目录与工作区内指向该目录的 symlink 均返回权限错误且文件不存在。
   保持 Guardian 拒绝数恰好为 1，防止把 Guardian 拒绝冒充原生沙箱拒写。
5. 新增可写根单测、路径别名/符号链接原生 OS 测试、可写正控及预检逃逸硬失败测试。
   宿主返回权限与真实文件状态联合验证，不以手工构造证明代替真实运行。

未改已有 externally_isolated 路径。该模式属于外层 OS 隔离，新增兄弟目录拒写证据只在
实际 workspace-write 模式下产生，并显式输出证据布尔值；不得将外层生产根只读保护
解释成相同的候选目录权限证明。本轮真实验证使用 workspace-write，非全权限替代。

## 协议依据

先读取本机 `codex-cli 0.155.1` 生成的 `ThreadStartParams` / `ThreadStartResponse` schema，
并对照 [OpenAI 官方配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。
使用现有 `sandbox_workspace_write.writable_roots`、`exclude_slash_tmp`、
`exclude_tmpdir_env_var`，未发明新字段或改写全局配置。
schema 快照在私有证据目录的 `repair-protocol/`。只修改临时候选 config，fixture 结束后恢复。

第一轮修复复验为 1 passed、2 failed：宿主省略了隐含 cwd，本地比较器错误地要求返回
重复根。随后将比较改为有效路径集合，只补回精确 cwd；首轮失败证据没有删除或覆盖。

## 验证记录

运行器：`run-native-failure-diagnosis.py`。分层选择 historical / boundary / consumers；
保存完整输出、真实退出码、JUnit、解释器/依赖/CLI 身份、测试和两份修改源码摘要。
每轮最长 300 秒，不以外层退出码覆盖 pytest 结果。旧证据保持原样。

**定向修复与验收通过；尚未提交、合并或安装，不构成整体发布许可。**

| 运行 | 结果 | 真退出码 | 总耗时（秒） |
| --- | --- | --- | --- |
| repair-default（初轮，已被后续修正） | 1 passed, 2 failed；有效根比较遗漏隐含 cwd | 1 | 20.030 |
| repair-default-r2 | 三项历史场景 3 passed，新增兄弟目录与 symlink 拒写成功 | 0 | 38.718 |
| repair-boundary | 46 passed, 30 subtests passed | 0 | 16.553 |
| repair-consumers | 15 passed, 55 subtests passed | 0 | 88.629 |
| repair-relocated | 同三项 3 passed，负例成功，临时根迁址 | 0 | 39.252 |

四组最终成功运行均无 skipped、failed；JUnit 会把 subtests 计入总数，因此对应边界
76、消费者 70 条 JUnit 记录，不将这些总数误称为独立顶层测试数量。重复运行不合并
虚增唯一测试覆盖率。全部使用相同 Python 3.10.7 / pytest 9.1.1 / PyYAML 6.0.3 /
Codex CLI 0.155.1；测试私有根间隔离。没有重跑全量。

边界组要求 `SULDE_REQUIRE_NATIVE_OS_EVIDENCE=1`，不允许以跳过替代真实 OS 证据。
消费者组覆盖普通/历史释放续接、记忆一致性及 Post 缺失恢复、字符串流识别原生场景。
源/目标任务内写入通过，原破坏性否决和未知对象否决保持有效，无授权转移。

原生候选 artifact generation（非生产安装）：
`0.2.5+codex.20260922005243-95a8cf2d92:61e1a4f9a97dbb3bf34b18237352464403f28c3dd7663a9cbaa42b2bbf786c03`。
默认根与迁址根输出同一 artifact 身份；loaded module 身份及否决事件仍由原测试验证。
本轮未改 Guardian 模块，不能要求 module digest 因测试基础设施修改而变化。

### 证据回读

本地目录 `.sulde/native-failure-diagnosis/<run>/` 保留 run.json、完整 pytest.log 和 JUnit。
下表为 run.json 的 SHA-256；每份元数据另绑定完整日志摘要，均已独立回读匹配。

| run | run.json SHA-256 |
| --- | --- |
| repair-default | c16ab4de69ecca3e8eb069b361f133db703e65851d275f1452570d07cc11ba38 |
| repair-default-r2 | ffd1a85afa29154c16fa2f7502db69c1f3d1b15b2f54bba1a108efe5c8c85862 |
| repair-boundary | 21f5327698427ef21080937b089f39b0942519d859a7691333e86e3f7d8b065a |
| repair-consumers | 43bd929fffe0d0066f1524fdeb94f4bdf1def5768d9be3157ebbc552de184c34 |
| repair-relocated | 8a86fa1478e04422f074358190ec67c6d2ef854a73618b4bb69e9c9107364d5d |

后三轮已增加源码摘要并与当前文件独立比较一致；前两轮保留原格式，不补写追溯字段。
当前交付基于 base commit 加工作树 diff，而非已提交 exact HEAD：

- 隔离 runner SHA-256：`c2e7cca6235d233523dda09b695ecb084dfeb4c6f1bea2e1f710372d6b73d596`。
- native canary SHA-256：`d7ffa4aed186a83a75a43e2844bff87ca940d776bc111eda27fb865eba1b8b83`。

修改源码/测试 AST 解析、`git diff --check` 通过；dev/main 工作树仍干净，引用未变。
私有证据继续排除在 Git 外；交付保留在原任务工作树，未清理未提交成果。

## 发布边界与剩余项

- 本轮 CLI 为 0.155.1，仓库审计常量为 0.154.0。没有修改版本常量绕过正式安装门禁。
  发布前须独立完成当前 CLI 契约审计；本轮原生测试不能替代整套兼容认证。
- Windows 实机 bootstrap、Linux 原生 bwrap、生产 Hook/调度未运行，不声明这些域已通过。
  Linux 命令构造路径规范化有单元覆盖，不等于 Linux OS 实测。
- 不恢复旧截断日志、不追认历史运行全绿；新证据只证明当前输入的当前结果。
- 不自动清理历史诊断证据或已合并的旧任务资源，避免与本次修复混杂。

## 沉淀候选（不直接入正式知识库）

- 问题：临时目录位置改变可以掩盖缺失的可写根声明，表面修复了测试却扩大/混淆边界。
- 处理：配置精确根、排除隐式临时根、读取宿主有效策略，再验证允许和拒绝两类真实写入。
- 根因依据：上一轮 raw/canonical 同物理目录对照与 EPERM 工具回执；本轮源代码及测试日志。
- 路由正例：Guardian 放行、executor EPERM，排查宿主写权限而非移除 Guardian 限制。
- 路由反例：Hook 实际拒绝未启动工具，不能用扩大 OS 写权限解决。
- 执行合格例：默认/迁址目录均成功完成任务内写入，未声明兄弟目录和 symlink 越界仍失败。
- 执行失败例：只迁移到宽松临时目录、禁用沙箱、伪造外层隔离，或只改 CLI 版本常量。
- 证据状态：诊断根因与本范围内修复 verified；不包含生产/跨平台发布结论。共享前移除私人路径和会话标识。

技能影响：dispatch-task 保持当前宿主配置；intent-guardian 明确从只读诊断到范围内修复；
kb-search 要求隔离外层权限噪声并保留真退出码；OpenAI Docs 用于核对可写根配置和协议，
而非凭经验猜测字段。没有为本任务引入任何模型升级或生产配置变更。
