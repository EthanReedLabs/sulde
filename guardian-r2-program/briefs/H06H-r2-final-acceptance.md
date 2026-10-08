/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06H-r2-final-acceptance.json

# H06H — 在统一控制边完成 R2 最终总纲验收

## Authority

- exact integrated base：`10ad8d876d74fe5c4dea8e3b1cc27e178078bdc2`。
- provider：Codex deep/high；不得调用、等待或依赖 Claude。Claude live 只作为协调端后续独立硬门，额度不可用时保持未满足，不得合成替代。
- H06H 追加式 supersede blocked H06D；不得复制、合并或改写 H06C/H06D 失败候选。可只读其事件和报告以保留 finding 语义。
- task 定义冻结 21 个 exact paths。managed worker 只允许写 `guardian-program/MASTER.md`、`tests/fixtures/r2-guardian-incidents/replay-cases.json`、`tests/test_r2_guardian_integration.py`、`guardian-r2-program/reports/H06H-r2-final-acceptance.md`；八个 task evidence 与九个 program evidence 均由协调器单写。
- 禁止 commit、install、scheduler mutation、production intent/KB write、push、merge、dev/main 修改、网络副作用和中断其他会话。

## 已采纳工程纪律

- `ap-0224`：判据必须匹配真实受限调用环境；不能把宽松 shell、空数据或合成 fixture 绿灯外推到生产。
- `ap-0244`：精确 Git/发布输入要同时绑定有限文件集合与共享元数据串行化；不能把 explicit path 压成仓库级权限。
- `ap-0039`：报告必须携带真实命令、退出码、可观察输出和未执行项；禁止只声明“已完成”。

## Candidate work

1. 将 `guardian-program/MASTER.md` 的 program evidence 数量从 eight 修正为 manifest 权威的 nine，并明确 native Windows 没有独立 kind，必须同时绑定在 task `system_tests` 与 program `final_traceability`。
2. 从 `guardian-r2-program/fixtures/incidents.json`、manifest、accepted H00-H06G 集成实现重新生成一个 exact fixture：`tests/fixtures/r2-guardian-incidents/replay-cases.json`。冻结 I01-I19、十三 failure axes、全部硬门与 live-only 分类；live/Windows/Claude/安装项只能标为需要独立证据，禁止 synthetic PASS。
3. 从当前集成公共边界重建 `tests/test_r2_guardian_integration.py`，覆盖 grant、broker、recovery、typed resource、progress、tamper/drift/retry/rollback/degraded/read-only ledger/content-safety 组合。测试必须调用生产公共函数；不得只验证 fixture 自己，不得从 broker 公共投影读取被有意遮蔽的 executable grant。tamper 通过 typed decision receipt/public settlement 边界注入。
4. 用真实红绿攻击证明 fixture 与实现有交叉约束：删减 incident/failure axis、放宽硬门、伪造 live evidence、修改 generation/subject/effect/verifier、让历史债务跨 subject、重复 effect、重复 waiting 或先 deny 后展示均必须判红。
5. 写 `guardian-r2-program/reports/H06H-r2-final-acceptance.md`，必须且只出现一次 `## 结果`、`## 过程`、`## 遇到的问题`、`## 解决方式`、`## 遗留风险与建议`。每条 `✅ 完成检查：` 必须是本轮可字面执行的真实命令并绑定 exit/output；历史证据用事件 SHA 与 item 标识，不伪装成当前命令。

## H06D findings 的精确处理

- `FR2-H06D-005`：worker 不再在窄 profile 内启动 formal runner。最终 full-suite 由协调器在完整 full clone 中显式把 cursor root 放在已授权 `/private/tmp`，并保留命令和 cursor 摘要。
- `FR2-H06D-006`：worker 不运行会在仓库根创建随机目录的相邻 AgentRuntime 组合；协调器在受支持 full clone/独立临时载体中运行完整套件并核验写目标，不把 setup PermissionError 当测试失败或 PASS。
- `FR2-H06D-007`：只通过 typed decision receipt 和公开 settlement/verification 边界测试 tamper；公共投影缺少 executable grant 是安全属性，不是缺字段。
- `FR2-H06D-008`：MASTER 修正为九类；H06H task definition 已冻结九个 program evidence exact paths；native Windows artifact SHA 必须进入 H06H `system_tests` 与 `program-final-traceability.json`，缺一不可。

## Worker verification boundary

- 只跑 H06H focused fixture/integration tests与相关无生产写入的小范围模块；始终使用 `PYTHONDONTWRITEBYTECODE=1 python3 -B`。
- 不在 managed worker 内运行正式 `run-isolated-tests`、production installer、scheduler 或 live canary。它们由协调器在候选独立复审和字节一致集成后串行执行，避免 cursor/随机临时目录越出精确 worker profile。
- effective diff 必须精确四个 worker writable paths；base、task/brief control projection hash、`.git`、`.codex-agent`、`.pyc` 均不得变化或进入候选。

## Coordinator final gates（worker 只能保留为未满足）

- supported full clone 必须有本地 `main`，并在所用 Python 中预检 `numpy`、`yaml` 及套件声明依赖；setup 失败不得计入测试结果。
- quiet-window runner 必须证明测试窗口内没有无法归因的 production writer；不得中断其他会话来伪造安静窗口。
- I01-I19、十三 failure axes、完整 isolated suite、failure injection、historical replay、installer rollback 均有独立 evidence。
- 安装、scheduler owner、Codex live、Claude live、native Windows 与 source/stage/installed/runtime/scheduler/hosts 同 generation 必须真实成立。
- 九类 program evidence 全部登记并验证，所有 inherited/new findings 有 append-only disposition 和 active resolution evidence，`final-check` 无 blocker 后才允许 complete。

## Terminal rule

managed run 成功只表示四路径候选和本地证据可交给协调端复审，不表示 H06H accepted、安装、production accepted 或 R2 complete。发现生产实现缺口时只在报告中给出精确红证据，由协调器登记 repair；禁止扩权修改其他路径。
