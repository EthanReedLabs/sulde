# T31 production live acceptance

## 结果

✅ T31 的安装后 live gate 已在 Sulde 自有仓库与原绑定 Codex thread
`01a00d6f-65b3-7663-b51b-f88684ffa561` 上完成。该 thread 在生产安装后通过
`codex resume` 启动新宿主进程，当前 installed runtime 记录了真实
`SessionStart`、`UserPromptSubmit`、`PreToolUse` 与 `PostToolUse` 观测；没有使用
synthetic callback、旧 receipt、外部项目 session 或伪造 hook 事件。

实时 operational projection 为 `ready`，全部交互 gates 为 true：当前 session 与
workspace 已绑定、task lane 为 `bound`、contract 为 active/enforce、host interactive
与 supervision 均为 live verified、native decision pairing 为 not-required/settled、
effect debt clear、artifact generation ready、scheduler 15/15 ready。

生产 generation 为
`0.2.5+codex.20260824084717:dbeaf8ce5708729998ffd79cfc0a367e216476d9cad756146212ce1b22d84b39`。
`com.sulde.kb-aging`、`com.sulde.codex-harvest` 与
`com.sulde.status-notify` 的 LastExitStatus 均为 0。

## 过程

- 从已发布 main `f019ee9a5d371475315f92ded0447acd8cb7ab00` 恢复同一 Codex thread，
  保留原 task lane 与对话历史，同时让新宿主重新发现已安装 Hook/Skill catalog。
- 登记当前安装版本的 `intent-guardian` Skill 摘要后，执行只读
  `git status --short` 往返；main 工作树干净，PreToolUse/PostToolUse 在当前 runtime
  上形成同一 call-id 的 verified roundtrip。
- 精确 session doctor 报告 session context、prompt control、tool guard 与 tool result
  均为 `live_verified`，host status 为 `interactive_ready`，supervision 为
  `live_verified`。
- 实时 `sulde-status.py --json` 投影确认 operational status `ready`、reasons 为空、
  scheduler managed=15/loaded=15/missing=0/failed=0、pairing settled、effect blocking=0。
- 实时投影发布快照后，稳定 statusline 不再显示
  `交互未就绪:host_interactive_fresh`，而是显示普通黄色 KB/记忆健康摘要。

## 遇到的问题与处置

1. 首次尝试把可信 doctor 与 JSON 解析管道组合，当前 Guardian 按合约拒绝复合控制命令。
   没有执行 doctor 或改变状态；随后改为单个精确 doctor 调用并读取原始 JSON。
2. `sulde-statusline.py` 与 `sulde-status.py --statusline` 都是启动热路径快照读取器，
   不是实时 readiness 计算器。安装后首次恢复提示之前的快照仍显示旧
   `host_interactive_fresh`，但精确 doctor 已为 ready。调用无通知的
   `sulde-status.py --json` 实时投影并原子发布快照后，状态栏与当前事实一致。
3. 全局状态仍为黄色，来源是历史事件观察违规、记忆待嵌与蒸馏时龄等独立健康域；
   它们没有进入 T31 operational readiness 的阻塞集合，不得冒充本次 live gate 失败，
   也不在冻结的 T31 源码范围内扩张修复。

## 未扩张边界

- 未修改产品源码、installed cache、launcher、native authority、LaunchAgent、生产
  contract 或 ledger。
- 未读取或修改 iquokka 等外部项目。
- 未新增实现任务；最终证据只在从 `dev` 创建的
  `release/t31-live-acceptance` worktree 中记录，并按 task → dev → main 合并。

## 沉淀候选

### Layer1 问题卡：快照状态栏不能替代精确实时 readiness

- **问题类型**：observability projection mismatch / diagnostic misuse
- **问题语境**：安装后恢复的真实 session 已由精确 doctor 证明 interactive ready，
  但启动热路径 statusline 仍读取上一轮后台快照并显示旧阻塞理由。
- **证据状态**：verified。精确 doctor 与实时 `--json` 均为 ready；刷新前快照红色，
  实时投影发布后稳定 statusline 不再报告交互故障。
- **路由正例**：状态栏与精确 session doctor 冲突，且状态栏实现读取有时间戳的持久快照；
  应以精确实时投影验收，并检查快照生产者是否已刷新。
- **路由反例**：精确 doctor 同样报告当前 session 缺少 prompt/tool roundtrip；此时不能
  把红色状态栏归因于快照，应补真实宿主证据或修复 Hook。
- **执行合格例**：保持状态栏热路径有界；验收调用单一精确 doctor/实时 JSON，刷新后
  再复读快照，同时分别报告 operational gate 与全局健康告警。
- **执行失败例**：把旧快照当成实时权限真值、为了变绿直接编辑快照，或把历史全局告警
  无条件升级为当前 session 的交互阻塞。
- **建议容器**：anti-patterns；由协调端判重，可能并入 host readiness/状态快照条目。
