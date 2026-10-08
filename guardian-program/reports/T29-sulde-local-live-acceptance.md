# T29 Sulde local live acceptance

## 结果

⛔ T29 已按冻结边界停止在 `blocked`，没有把不满足的 15/15 scheduler
门冒充为通过，也没有继续触碰已经完成业务任务的 iquokka 工作区。

已确认 T27/T28 的源码、测试、`dev` 到 `main` 合并和官方安装证据仍然有效；
两条 iquokka 会话只保留为历史问题复现证据，不再是 Sulde 发布依赖。当前稳定
launcher、installed generation 和 runtime owner 一致，但
`com.sulde.kb-aging` 在当前 generation 上退出码为 2，因此当前调度真值为
14/15，T29 不能进入 live canary 或总纲验收。

实现结果：本任务只新增控制面定义、冻结卡、任务 brief、本报告和 append-only
事件；未修改产品源码、生产 contract/ledger、安装缓存、LaunchAgent 或外部项目。

## 过程

- 记录 `F27-002`，将“外部业务项目 task epoch”从 Sulde 发布验收门中移除；
  以 T29 取代 T27 的验收边界，同时完整继承 T27/T28 已验证交付证据。
- 在 Sulde 自有边界检查当前官方安装：generation 与 launcher 一致，15 个 actor
  全部加载，但 `com.sulde.kb-aging` 的当前运行退出码为 2。
- 读取 actor 日志并做无写入 dry-run：installed runtime 默认执行失败，报
  `not a git repository`；同一脚本显式传入源仓库 `--repo` 时成功分析 366 篇文档。
- 由此记录 `F29-001` 并将 T29 转为 blocked；拒绝把 LaunchAgent 手工指向开发
  checkout，因为这会让不可变安装依赖可变源码目录，也绕开官方安装链。

## 遇到的问题

- `kb-aging.py` 默认从脚本位置推导仓库根，并用 `git ls-files` 与逐文件
  `git log` 取得文档清单和历史时间。
- 官方安装会把 actor 切换到不可变 installed runtime；该 runtime 包含
  `knowledge/MANIFEST.json` 和知识文档，但按设计不包含 `.git`。
- 因此该 actor 在源码树测试可通过，在真实安装环境却必然失败；此前每轮测试
  未覆盖“无 `.git` 的打包 runtime”这一部署拓扑。

## 解决决定

用户已确认只创建一个有界后继 T30：在源码仓生成并打包可验证的不可变知识历史
凭据，让 `kb-aging` 在无 `.git` runtime 中读取它；凭据缺失、被篡改或与 corpus
不一致时 fail closed。T30 必须补 packaged-runtime 回归，并通过官方链重装后证明
该 actor 成功及 scheduler 15/15。

## 遗留风险与建议

- T30 完成前，当前官方安装的 scheduler readiness 仍为 14/15；不得把 actor
  “已加载”误写成“已就绪”。
- post-install Sulde 自有 Codex live canary 和程序级 final-check 仍未执行；它们
  必须在 T30 官方安装与 15/15 验证后串行完成。
- 本任务没有授权其他功能、清理或外部项目工作；后续发现若不阻断既定验收，应只
  记录为建议，不得扩张 T30。

## 沉淀候选

### Layer1 问题卡

- **问题类型**：release-topology mismatch / bug-fix
- **问题语境**：后台 actor 在源码 checkout 中依赖 Git 元数据，但官方安装把它
  重定位到不含 `.git` 的不可变 runtime；源码测试与真实部署拓扑不同。
- **已确认根因**：文档年龄输入没有被建模为发布 artifact 的显式 provenance，
  actor 在运行时隐式执行 `git ls-files` 和 `git log`。
- **证据状态**：verified。当前 generation 的 LaunchAgent 退出码为 2；同一
  installed 脚本默认 dry-run 失败，而显式指向 Git checkout 时退出 0 并枚举
  366 篇文档。
- **路由正例**：调度脚本需要源代码历史，生产 artifact 不含 VCS 元数据，应在
  构建期生成、绑定 corpus 并验证 provenance。
- **路由反例**：运行时只依赖 artifact 自带静态内容且测试已经在完全相同的无
  VCS 拓扑执行，不需要额外历史凭据。
- **执行合格例**：构建期生成确定性历史清单；installed runtime 在无 `.git`
  环境校验清单和 corpus 绑定后运行；缺失、篡改、错 corpus 全部拒绝。
- **执行失败例**：把生产 LaunchAgent 指向开发 checkout、用文件 mtime 冒充历史，
  或在测试中始终保留 `.git` 而宣称覆盖了安装态。
- **建议容器**：anti-patterns；可复用内核为“凡运行时隐式依赖 VCS 的调度任务，
  必须把所需 provenance 纳入 artifact 合约并测试真实部署拓扑”。
