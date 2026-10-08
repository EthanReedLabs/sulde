# R14：Python 3.9 受保护身份读取兼容性

日期：2026-09-13。承接 R13 安装后黄色健康状态的只读核验。
capability_tier: balanced

## 冻结范围与控制面

- 基线 dev：`4fd241d87aeac150587883dd58914017a3d76eb0`。
- 分支：`task/r14-status-python39`；隔离目录：`.worktrees/r14-status-python39`。
- 原生 revision 2 批准回执：`8964c3bfd32d3adb845de1d4cf504ee373672592250dcdc491bfdc814833c2bf`。
- 当前会话通过原生 workspace handoff 绑定任务目录，回执：
  `ccdc0742986440801eb11cc2300dad21ef210f5994ce4f1876dabe436e90376c`。
- 只改三个跟踪文件：`scripts/kb/sulde_paths.py`、`tests/test_sulde_paths.py`、本报告。
- 只交付本地源码、专项测试、报告及 dev 集成；不安装、不推送、不合 main、不触发调度。
- 不修改生产 pointer、账本、SELF、同步配置、cache 或其他任务。任务证据不依赖记忆图谱。
- 停止线：本问题专项通过后提交并合入干净 dev、清理本任务；新发现只记录，不自动扩容。

## 根因与最小修复

已安装健康收集在 `/usr/bin/python3` 3.9.6 中失败；独立 doctor 仍证明 scheduler
16/16 ready、无失败 label、当前效果债务为零。两者并非同一解释器/入口的测试。

只读堆栈为：

```text
sulde-status.collect
  -> operational_readiness.project
  -> _current_effect_truth -> intervention.load_projection
  -> sulde_paths.contract_identity_digest -> _protected_json
TypeError: stat() got an unexpected keyword argument 'follow_symlinks'
```

`Path.stat(follow_symlinks=False)` 在生产 Python 3.9 不可用。异常被外层收集器捕获后，
operational readiness 变为 unavailable，scheduler 则为 scheduler_projection_unavailable。
不能据此认定 launchd 真的失败，也不能以开发 Python 的通过覆盖生产解释器。

实现仅替换为 `Path.lstat()`。继续读取链接自身的元数据；保持既有 regular-file、
symlink、owner-only、JSON 对象与 identity map 摘要校验，未改身份计算或迁移账本。
这不是并发文件替换/TOCTOU 安全重构，不声称解决既有读取竞态。

## 验证与反例

新增 9 项测试，测试数据全部来自临时合成目录。保留原有 3 项路径测试。

- 普通私有 JSON：0600、0400 均可读，内容、mtime、权限不变。
- 既有及断裂 symlink 拒绝；宽权限、错误 owner、缺失文件、目录、错误编码/JSON/类型拒绝。
- 构造独立的已迁移 pointer 与密封 identity map；验证 paths、approval、correction、
  intervention、native journal 五个真实读取入口保持历史身份，且两份文件字节不变。
- 新合同不继承旧身份；篡改 identity map 必须失败。没有通过调用迁移写入器来制造
  读取器的前置状态，也不访问操作员的生产 pointer。

| 运行 | 结果 |
|---|---|
| 修复前，Python 3.9 新增普通文件与身份读取两项 | 失败，7 个 subtest errors，均为上述 TypeError |
| 修复后，Python 3.9.6 `tests.test_sulde_paths` | 12/12，0 skip，0.059 秒 |
| Python 3.9.6 paths + statusline | 29/29，0 skip，0.085 秒 |
| Python 3.14.6 paths + home_migration + statusline | 42/42，0 skip，0.240 秒 |
| `git diff --check` | 通过 |

```sh
/usr/bin/python3 -B -m unittest tests.test_sulde_paths tests.test_sulde_statusline -q
python3 -B -m unittest tests.test_sulde_paths tests.test_sulde_home_migration tests.test_sulde_statusline -q
```

专项通过不等于全仓 release-level 通过；未进行新的生产安装或 live 修复验收。
两份原始通过日志保存为 `.sulde/public-export/r14-python39.log` 和
`.sulde/public-export/r14-python314.log`，收尾时归档到长期 dev 工作区同一路径。

## 保留问题：不是本轮新增任务

1. 原黄色快照生成于 03:42:05 UTC，LIFE state 03:41:44 UTC 为 degraded；
   L2/L3/L4/evolution 全为 ready。health_domains 指向此前心跳
   `self_fixed_sections_changed`（最新记录 00:10:30 UTC），不是处理队列失败。
   本轮不改 SELF，不重跑 heartbeat，不将黄色改成绿色。
2. 汇总只读状态还报告 268 个 historical event contract violations、1 个 invalid store；
   当前 effect_blocking/interventions_open 为零。没有逐条核验，不把历史计数当成本会话债务。
3. 同步域报告 migration_required / repository_outside_current_data_root_or_unsafe；
   不推断远端结果，不重试、不迁移。
4. Python 3.9 原有 home_migration 的单个身份测试在生产读取函数之前就失败：
   `sulde_home_migration._records` 同样使用 `candidate.stat(follow_symlinks=False)`。
   此为迁移执行器的独立兼容性限制，未修复。该次运行 4 tests / 1 error 保留为失败，
   不以 Python 3.14 全部通过替代，也不宣称 Python 3.9 支持整个迁移执行流程。
5. 新任务开始时 completion anchor 只有只读权，doctor 显示 task_lane_bound=false；
   通过显式 revision 和 workspace handoff 正常继续，没有复用旧安装授权或删除账本。

## 中途执行问题及处置

- 两次症状 KB 查询未命中适用条目；没有采纳无关平台结果。
- 假定存在的 sulde-status.py 快捷入口实际不存在。只读确认正式 job 的目标后，
  从已安装 runtime 运行其明确支持的 `--json --read-only`；不新建快捷入口。
- worktree 初次创建受沙箱 .git 写入限制；经宿主原生许可后正常创建，不绕过守卫。
- handoff preview 不接受 `current` 作为工作区路径；改为 prepare 返回的精确目标，
  仅一次 handoff 决定落账。
- 原生确认、只读回读、源仓/安装态区分遵循 intent-guardian；dispatch-task 仅约束
  当前 Codex 的任务正文，不输出型号前缀、不启动另一个宿主或子 Agent。

## 沉淀候选（Layer1，未直接入库）

### 任务与意图

- 问题类型：regression / host-inconsistency。
- 目标与真实预期：安装后健康检查能实际运行；范围冻结，不因残留告警不断扩大任务。
- 触发：后台系统 Python 比交互/开发 Python 旧，且存在已经迁移的受保护身份 pointer。

### 观测与证据

- 症状：开发测试通过，后台 TypeError 被折叠为 readiness unavailable。
- 根因：Path.stat 的参数兼容性；证据 verified：生产只读堆栈、合成 red/green、双解释器测试。
- 排除：实际 scheduler 全部失效；只换 cwd 能解决；把异常吞掉就算通过。
- 做法：采用等价且旧解释器支持的 lstat，保留安全校验，验证所有身份读取消费者。
- 限制：迁移执行器、生产新版安装、心跳和同步域均不在该证据覆盖内。

| 样本 | 内容 | 预期 | 原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 系统 Python 的文件 API 抛参数 TypeError，开发 Python 正常 | apply | 解释器差异直接命中堆栈 | observed |
| 路由反例 | 相同 API 正常但目标文件为 symlink/宽权限 | skip | 是预期安全拒绝，不是版本兼容 | constructed |
| 执行合格例 | lstat 在生产解释器通过，旧身份不变且不安全文件仍拒绝 | pass | 同时覆盖正路径和安全不变量 | constructed，已运行 |
| 执行失败例 | 只在新 Python 测试或捕获 TypeError 后放行 | fail | 未覆盖真实解释器或丢失安全校验 | constructed |

上浮时泛化个人路径、版本、会话与提交；复用内核为“按真实执行解释器验证受保护读取，
将迁移执行器与已迁移状态读取器的证据分开”。建议 anti-patterns；消费者为安装验收和回归矩阵。
