/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06E-codex-help-authority.json

# H06E — Codex help authority 环境归一化 repair

## Frozen authority

- base：`f0e845617867c1710b636205c6798d03140d1646`。
- provider：Codex deep/high only；不得调用 Claude。
- 只允许修改 task definition 中六个 exact paths；不得 commit、install、改 scheduler/生产 KB、push、merge 或触碰 dev/main。
- `PYTHONDONTWRITEBYTECODE=1`、`python3 -B`；编辑只用 `apply_patch`。

## Confirmed root cause

H06D 证明同一 `codex-cli 0.150.1` 的三份 help stdout 会受父进程 PTY/颜色环境影响；sandbox 内还会额外出现唯一已知非致命诊断：

`WARNING: proceeding, even though we could not create PATH aliases: Operation not permitted (os error 1)\n`

结果是 installer seal、PTY run、sandbox run 与 external run 得到不同 raw digest，虽然 executable/version/help 语义未变。不得简单放弃 stderr、只做 token 包含检查或关闭 digest gate。

## Required repair

1. 在 `codex_cli_contract.py` 中建立共享纯函数：
   - 为 version/help probe 构造固定环境，至少消除 `TERM`/颜色变量造成的格式差异并显式设置非交互 no-color 语义；
   - canonicalize 每份 help 的 stdout+stderr；仅允许精确剥离上面的完整 PATH-alias warning，不能用 substring/regex 宽泛忽略；
   - 返回三份 canonical bytes 的同一 observation digest。
2. `agent-runtime.py` 与 installer 必须调用同一 helper；禁止复制 warning 字符串、环境逻辑或 hashing 实现。
3. 保持 executable path/digest、exact `codex-cli 0.150.1`、required help tokens、return code、strict profile、app-server initialize、broker/runtime/tree/generation 所有现有 gate。
4. 负样本必须证明：
   - PTY/no-PTY 与“无 warning/精确 warning”得到同一 observation；
   - warning 多一个字符、第二条诊断、未知 stderr、ANSI/语义 stdout 变化、缺 token、非零 rc、0.149/future/alias 与 re-signed authority drift 全部拒绝；
   - caller 环境 mapping 不被修改。
5. 报告记录 FR2-H06D-002/004 根因、修复、命令、退出码、skip、风险，并明确未安装、未完成 H06D/R2。

## Verification

- 先运行新增的 shared helper、runtime preflight 和 installer native-authority focused tests。
- 再运行 `tests.test_agent_runtime` 与 `tests.test_codex_plugin_install` 受影响组合；managed worker 不在外层 profile 内启动 formal runner，协调器会独立运行单层 formal。
- task report 必须通过 worker report schema，且 diff 只能包含六个 exact paths。
