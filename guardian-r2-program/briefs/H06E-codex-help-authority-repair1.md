/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06E-codex-help-authority.json

# H06E repair1 — 关闭控制字与真实 PTY 证据缺口

## Frozen continuation

- 沿用 H06E task definition、base `f0e845617867c1710b636205c6798d03140d1646` 与六个 exact owned paths。
- 这是 run1 的原任务返修，不新建任务、不丢弃 run1 证据；不得 commit、install、改 scheduler/生产 KB、push、merge 或调用 Claude。
- 编辑仍只用 `apply_patch`；保持 `PYTHONDONTWRITEBYTECODE=1`、`python3 -B`。

## Independent blocking finding

`FR2-H06E-001` 已由协调端登记。run1 的 `canonicalize_codex_help` 只拒绝 `ESC`，独立攻击证明它错误接受：

- ANSI C1 CSI `U+009B`；
- carriage return `U+000D`；
- backspace `U+0008`；
- NUL `U+0000`。

另外，run1 的“PTY”测试只改变环境 mapping，没有运行真实 PTY 与 non-PTY 两种父宿主；真实 0.150.1 roundtrip 只覆盖 pipe/capture_output。

独立真实探针进一步确认 `FR2-H06E-002`：run1 固定了环境但仍继承父进程 stdin。相同 no-color 环境与精确 warning 下，非 TTY digest 为 `b20b7135…`（长度 5729/3957/3206），真实 PTY digest 为 `3da94b7a…`（5929/4037/3342）；显式空 stdin 后恢复为 `b20b7135…`。

## Required repair

1. 共享 helper 必须拒绝 help stdout 中除 LF 外的 ASCII/C1 控制字符；如真实 audited CLI 确实需要 TAB，必须先用真实字节证据证明并只精确允许 TAB。不得只枚举 ESC/C1 CSI，也不得用会漏掉 CR、BS、NUL 的正则。
2. 增加至少 `U+009B`、CR、BS、NUL 的失败注入；它们必须在 installer 与 runtime 使用的同一共享入口失败。
3. 共享 probe 规范必须同时固定环境与 stdin：runtime 的 version、三份 help、profile-help 命令显式使用空 stdin/EOF；installer 对应五次 runner 调用显式传入其既有的空输入参数。调用方不得各自发明不同的交互边界。
4. 增加真实 `codex-cli 0.150.1` 双环境观测：一个普通 non-PTY 父进程和一个真实 pseudo-terminal 父进程，都由同一小型 probe 调用 production probe spec、三个真实 help 命令和 `canonical_codex_help_observation`；断言三份 canonical surface 与 digest 相等。不得只 mock `isatty` 或修改 TERM 字典冒充 PTY。
5. 保留 run1 已通过的精确 warning、unknown stderr、return code、required token、version、re-signed authority、profile/broker/runtime/tree/generation 负样本。
6. 报告追加 repair1：保留 run1 红灯/绿灯与环境性 skip，明确独立审查为何打回、repair1 新证据、命令/退出码/计数以及未安装、未完成 H06D/R2。

## Verification

- 先让新增四类控制字和真实 PTY 对比测试在旧实现上失败，再修复转绿。
- 重跑 run1 的 12 项 focused/real 组合与 `tests.test_codex_plugin_install`。
- managed worker 不扩权运行仓库根临时 fixture；协调端会在单层 formal 环境独立验收。
- 最终 effective diff 仍必须精确等于原六个 owned paths；两份 `guardian-program` authority 投影不得修改。
