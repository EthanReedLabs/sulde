# S3-C 后续修复任务：安装窗口可用性与分域健康投影

capability_tier: deep

状态：冻结候选，待诊断独立复核及源码写入授权。本文件不是授权凭据。
执行宿主：当前Codex；基线dev eacee08，实施前记录精确HEAD/安装代际并确认
差异。新任务分支从最新dev创建于仓库.worktrees/guardian-update-continuity，
不能直接改dev/main、当前安装目录或其他任务的WIP。

## 一个有界交付，不逐测试派单

目标：让升级期间诊断入口与故障观测不被同一个被替换目录同时切断；背景
健康与交互授权分开解释；不增加放行权限、不取消摘要校验、不扩大恢复操作。
本任务包括诊断→最小修复→注入→实际入口→模块→统一集成测试→一次集中
独立复核。普通失败不要求用户再次发送继续。生产安装/远程动作/真实模型
调用/资源删除另行授权，不以这些未授权项阻塞源码有界交付。

## 三项工作包与所有权

### A：分域状态（可独立开发）

主文件scripts/kb/sulde-status.py、sulde_status_snapshot.py；必要时对应
tools/kb-mcp只读返回面及其测试。保留LIFE global状态、来源时间/代际与原因，
同时明确background/scheduler和interactive未观测。后台无lane不是失败
执行，但真实L2/3/4/evolution、scheduler/持久化、过期/损坏仍报告问题。
旧快照兼容应保守，不增加每次MCP的深扫或隐藏全局unknown。

### B：稳定入口与安装切换（单写者）

主文件scripts/release/install_codex_plugin.py、必要的launcher生成模块；
选择既有稳定入口机制，避免第二套授权/控制面。先在真实installer failpoint
中证明失效窗口，才改代码。保证一个已启动/旧会话持有的入口，其必要adapter
与依赖在registry remove/add和alias替换期间可达且身份可校验。不得猜最新
runtime目录、持旧权无限执行、删除校验，或单纯增加sleep/重试。
路径可达与模块/代际权限分别处理；物质动作无法证明时继续fail-closed。
整树替换/别名发布必须保持原事务恢复和精确回滚，不能只修成功路径。

### C：故障观测（待B接口冻结后接入）

主文件integrations/codex/plugins/sulde/scripts/run-hook.sh、相关既有
observer/launcher接线与对应测试。记录器不依赖正在替换的adapter路径；
仅追加有界脱敏故障事实，含阶段、事件关联与身份已知/未知，不采命令/prompt/
密钥。无可用解释器或无法写盘时明确coverage unavailable，不能写成clear。
只记录，不重执业务命令，不修改原权限决定。正常成功热路径不加重扫描。

A/B可以两名subagent独立worktree并行；C在B稳定接口后接线。每名只编辑
自己文件并先自测，协调端集中集成一个分支。共享文件只能一个owner，不互
覆盖。遇到超出上述路径的必要变更，先给出影响解释并修订范围。

## 冻结验收

1. 正常对照先成立；复用diagnose-window.py有效输入，将外部桥桩替换为
   真实installer/launcher边界夹具，不能把桩测试叫生产链验收。
2. 相同夹具/输入/断言在基线与候选运行：故障可达性、Read降级、记录存在，
   旧失败须到达目标边界，新通过须实际消费修复。ps仍按既有受支持范围处理。
3. 覆盖registry remove/add、launcher发布、alias发布、异常回滚与硬退出恢复；
   在窗口内真实触发Hook，而不只在promote完成后测试。
4. Read正常可用；写入/未知/伪造代际/摘要漂移/伪造恢复入口仍拒绝；日志失败
   不制造权限，未送达不记效果成功。两个session不共享授权。
5. 状态矩阵：scheduler ready但无interactive身份；真scheduler故障；LIFE
   持久化/子域失败；损坏/缺失/过期快照；真实交互缺口。不能无条件变绿。
6. 每模块先自测/静态门，统一分支跑消费者与交互后一次全量（本任务触及安装
   事务和Hook共享面）；最后独立复核。若实际只改文档，不跑全量。
7. 正常入口交叠A/B至少5组，median预算max(20ms,5%)、P95
   max(50ms,10%)；不新增监督模型调用。安装分项记录，不能跨时段宣称提速。

## 证据、预算、停止

每份记录绑定实际源码/测试/夹具/环境/命令/exit/断言与前后摘要。
Optimus /Volumes/Optimus/Sulde/tasks/guardian-unified-plan-20261004/S3-C-repair/
唯一run目录，自排除hash清单；普通测试不覆盖正式历史证据。未挂载不创建
伪挂载目录，保留本地待归档状态。
两次相同失败无新证据改诊断方法；不能增timeout、放松断言或反复微派单。
范围/权限扩大、不安全恢复、外部前提或预算需决策时停止；不自标accepted。
交付区分已证旧缺陷、候选修复、夹具错误、生产未验证。不要将本批关闭解释为
U07/U08/U11/Windows/历史债务和统一计划所有待办已完成。
