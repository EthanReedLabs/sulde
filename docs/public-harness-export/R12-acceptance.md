# R12 Pro 安装后验收与交接

日期：2026-09-13。依据：`R12-release-plan.md`、原安装合同 revision 11、
当前交接合同 revision 194。机器可核对的摘要见
[R12-acceptance-evidence.json](R12-acceptance-evidence.json)。

## 当前决定

R12 的源码集成、候选验证、正式安装及当前 Codex 交互验收已完成。本次将原先留在
忽略目录的安装结果纳入版本管理，保留原件与 SHA-256；本提交仅交付文档，不改变
已安装源码身份，也不代表重新运行了完整测试套件。

**整体发布验收仍为 blocked：`com.sulde.auto-sediment` 最近退出码为 2。**
16/16 labels 已加载，但不能据此宣称所有后台功能正常。当前 doctor 顶层 `ready`
对应 `readiness_scope=interactive`；它同时明确报告 scheduler `degraded`。验收须读
分域结果，不能只引用顶层状态。

## 已完成链路及独立回读

| 检查项 | 证据与结果 |
|---|---|
| 集成源码 | `ab3eef2223c273a4e9bc06e31018b2661182e40b` 已合入 dev；唯一版本提交 `ee5caa9fd1ecae0fdf72a8bb8f8e67ec633ef148`，tree `9b3b4fe24e02943e069385f093584e1734c96b6a` |
| 既有 scoped 测试 | R12 28/28，零 skip，1.184 秒，零生产写入；已重算原 tests.log SHA-256，与原报告一致 |
| 正式候选 | `pro-public-harness-20260913-bound-python`：verified → promoted，`promotion_consumed=true`、`promotion_error=null` |
| 候选完整性 | 按 installer canonical JSON 规则独立重算 receipt，匹配 `f49e0fa352866c88090bb7f4a434a5691afcccd8f5a0d953c87699d6d9a4ccea` |
| 安装效果 | cachebuster 与 install grant 各消费一次；attempt `att-3815fff89e1e29c132a29f43`、`att-ed72fd2a8b17e28a4afc9470` 均由注册 verifier 独立结算，原合同 pending/open 为 0 |
| 安装版本 | `0.2.5+codex.20260913012848-c721a575c1`；runtime tree `fec56d3657e7aebf618bb4a6d0aede3dbdcac44cac7842befe955cb6b62646bf` |
| 制品与缓存 | 官方 artifact 的插件目录与 installed plugin 逐文件递归比较无差异；当前 doctor artifact generation 为 ready |
| 发布描述与 owner | deployment `generation_verified`、owner `active`，两者 operational_ready=true；activation `b33a96b25cca403ab297e45f88fe4d94` |
| 原 MCP 验收 | 官方安装路由新 stdio 进程完成 17 个请求，8/8 search、8/8 get；8 篇文档均记录 source/runtime/MCP 字节一致，2.051 秒 |
| 当前 MCP | 当前会话 `kb_status` 实际调用成功，返回后台快照 degraded；这证明传输可用，不证明整个后台健康或本会话有新的 MCPInitialize 观测 |
| 当前交互 | SessionStart、prompt、tool guard/result、turn reconcile、host approval 均 live_verified；interactive ready，当前效果债务 clear |
| 当前真实拒绝 | 负向 canary 的删除命令被真实 PreToolUse 拒绝；finalize 独立验证 marker 保留并清理；最终 marker 不存在 |
| scheduler | 宿主只读 launchd 探测：16/16 loaded、无 missing/retired；auto-sediment last exit=2，因此该域 degraded |

当前 canary proof 为
`0f58c963585620b9e930a8006baf9b261cfe7cb51f37b9c5b48fb8b09d0a84e9`，
started event 为 `14a72f94c4f541c231de51b9`。它同时绑定当前 artifact generation 与
loaded module generation `4eebf26591f75d8100704ecbbde2df0d8e0eae472688067be63ceee05ccc87d0`。
没有把 prepare 创建 marker 的行为描述为“全程零写入”，也没有把 fixture 拒绝冒充宿主拒绝。

原候选刻意未观测 native permission UI 与生产 scheduler host；这些原值保留在证据 JSON。
原发布会话的 live proof `6473611d7438f83e934ecb41ed3e683aceae87bc13a2cad0fea2a69ebf1f9fc0`
以及本次新 proof 分别记录，不转移旧会话 authority。新会话静态 Skill 已加载当前版本，
无需再次安装来补静态目录刷新。

## R12-F01：安装包被当成 Git 源码仓

证据状态：verified。源码调用链、安装路径只读复现与宿主退出码一致：

1. `auto-sediment.py:26` 的 `REPO_ROOT` 来自脚本所在目录。
2. `run_command`（151 行）默认在这个目录执行命令。
3. 普通调度参数仅为 `--max-candidates 5`，`main`（1592 行）首先进入
   `run_in_isolated_worktree`，在检查是否有待处理候选之前发现 Git common-dir。
4. `run_in_isolated_worktree`（478 行）对 installed runtime 执行 `git rev-parse`；
   该目录是分发制品，没有 Git checkout，查询失败后主入口返回 2。
5. 只读重放同一 Git 查询返回 128；没有启动 auto-sediment、运行 LLM、生成沉淀或重载任务。

日志末尾反复出现 `cannot locate git common directory`；该日志最后修改时间为
2026-09-13 10:30:04 +0800，与该 label 的 10:30 调度相符。末尾行无独立时间戳，
不据此断言日志中每条历史错误都属于这次安装。此前日志已有同类失败，故本轮确认
当前缺陷，但不把首次引入版本归因于 R12。

安装时 16/16 loaded、无失败的历史快照保持原样；这证明调度装载成功，并未覆盖之后
定时触发的实际业务路径。当前 runtime 的摘要检查通过，故此处不应按摘要污染处理。

后续修复需明确只读 runtime 与可写知识源码/提案仓的不同角色，受管 worktree 必须来自
显式指定且验证过的 Git 根；不能仅给 LaunchAgent 补 `WorkingDirectory`，因为本函数
自行覆盖了 cwd。也不能把 `.git` 塞入 installed cache 或设孤立运行环境变量跳过门禁。
回归至少覆盖“安装包没有 .git”的真实入口，以及缺失/无权访问目标仓时的无写入拒绝。
修复部署后仍须独立确认实际调度执行成功，而不只重装清空退出码。

本交接只记录修复边界；没有新增实现任务、修改源码或执行后台写入。

## 执行中遇到的问题与处置

- 旧会话 r193 指向早期 Guardian V3 和已删除的 worktree。本次通过只读 Git/发布原件
  找到 R12 真正已完成的版本，用户确认后以 r194 冻结文档收尾范围。
- 一次组合只读命令因包含 `propose-revision --help` 被当作改变上下文的控制动作拒绝；
  单独 help 可执行。未因此修改分类器。
- 首张收尾 proposal 在进一步诊断后因 material baseline 改变而失效，原生请求未执行；
  诊断完成后刷新同一收尾范围并由原生卡 applied，没有复用失效审批。
- sandbox 内 doctor 无法观察 launchd，且把外部审批证据缺失投影为 cas_mismatch。
  同一只读 doctor 在宿主可见边界确认配对正常并发现真实 auto-sediment 失败；没有删账本。
- 原安装报告记录的 venv/基解释器身份差异、热切换期间一次只读 Hook 拒绝仍保留：前者
  未发布的候选没有被冒充成功，后者恢复后的 ready 不抹去曾发生的可用性间隙。

## 交付和保留边界

本轮仅将这份报告和证据 JSON 在独立 task worktree 中提交，再 fast-forward 合入本地 dev。
文档归档验证通过不等于 scheduler 功能修复通过；总体发布门仍由 R12-F01 阻断。
main 保持 `bd216b3d29e37b1aaf0e6be0c930b5221a925562`，origin/dev 保持
`11c8f9063da32606caeccd4355be8d8d5b44b9c8`；没有远端 push 或第二次安装。

原安装报告、候选 state/receipt 和 MCP 原件继续保留在 dev worktree 的
`.sulde/public-export/`；原集成测试原件保留在 public-harness-export worktree。
证据 JSON 列出精确相对路径与文件哈希。只清理本轮创建的文档 task worktree/branch，
不删除保留原始证据的其他 worktree。Windows native、Claude live 仍不在本次验收范围。

## 沉淀候选：分发制品中的后台作业隐含依赖源码 Git 根

- 问题类型：bug-fix / workflow；任务目标：正式安装后后台沉淀可以按调度运行。
- 触发：从不携带 `.git` 的安装包执行默认 auto-sediment 路径。
- 预期与实际：scheduler 注册成功，但首次业务入口在 Git 根发现处失败并返回 2。
- 根因：runtime 根被复用为可写 Git 源码根；证据 verified，首次引入版本 inconclusive。
- 一手依据：当前 launchd 16/16 + last exit 2、日志末尾、上述四处源码、只读 Git 查询。
- 排除：当前不是 generation 摘要漂移；不是仅更改启动 cwd 就能解决的路径问题。
- 正确做法及验证：修复尚未实施；上述显式仓库绑定和制品入口回归属于待验证方案。

| 样本 | 内容 | 预期 | 判定依据 | 来源 |
|---|---|---|---|---|
| 路由正例 | 安装包运行正常，定时写作业找不到 Git 根 | apply | 分发 runtime 与源码仓身份混用 | observed |
| 路由反例 | 真实源码 checkout 因 index.lock 被占用无法提交 | skip | 有 Git 根，属于并发问题 | constructed |
| 执行合格例 | 无 .git runtime 通过显式可写仓完成受管工作，独立验证成果 | pass | 真正覆盖分发后的业务路径 | constructed，未执行 |
| 执行失败例 | 仅检查 labels loaded，或用源码 checkout 测试冒充安装包成功 | fail | 绕过真实故障前提 | observed / constructed |

上浮时删除个人路径、提交、会话及版本标识；通用内核是区分运行制品与可写源码身份。
建议容器：anti-patterns；消费者：scheduler installer、auto-sediment、发布验收。
检索未找到可直接采用的同根因条目；本轮仅保留候选，未写知识库或记忆图谱。
