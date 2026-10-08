# S3-C 源码候选：有界修复已证，完整目标未达标

日期：2026-10-06。基线 dev `eacee0824f8ea0199f780a977e775856c1f6bf32`。
集成分支：`task/guardian-update-continuity`。本次修复限独立工作树，不改变生产。

## 结论与停止原因

A（健康分域）和 C（已经启动的 Hook 的保守降级/独立故障观测）已完成有界
源码验证。B 的已有 symlink 原子替换已证；**B 完整连续性目标仍 blocked**。
宿主若先删除旧绝对入口，旧会话随后才发起 Hook，插件代码尚未运行，无法
通过已打开 FD 保活。安装器窗口测试明确观测该路径不存在，不是推测。

不能把该项降级为普通“生产未验收”，也不能自改冻结标准后标 accepted。
本轮未启动已知无法闭合目标的全量测试，不合 dev、不安装、不推送。
下一阶段需要宿主稳定 Hook 注册入口及旧会话迁移契约的设计/范围决策。
这与 A/C 已验证的有界修复不矛盾，失败候选与证据继续保留。

## 实现与所有权

- A 独立分支 `task/guardian-update-health`，提交 `ba636d7`（集成 `7875a15`）：
  保留 LIFE global status、原因、时间、代际；提供 background 与 interactive
  分域，不把后台缺人类 lane 标成执行失败。真正的 scheduler/持久化/子域故障、
  数据缺失/损坏/过期仍异常。MCP 仍只读有界快照，旧快照不推断交互授权。
- B 独立分支 `task/guardian-update-entry`，提交 `59b17eb`、`6c46eaa`
  （集成 `1952444`、`60ef679`）：已有 symlink 用单次 replace 发布；异常保留
  旧链接、漂移拒绝覆盖，真实安装 failpoint 与 recover-only 回读验证。
- C 集成分支单写者：`d51f723`、`d058557`、`d4045bb`、`410df0d`、`822dbaf`。
  wrapper 在读取宿主 payload 前打开 observer/classifier 的 FD；原 fallback
  优先以保持既有 native recovery，依赖无法加载才进入同一静态分类器。
  记录桥缺失、局部入口失效及检查/启动竞态，不重执工具，不复制授权或结算效果。
  非零 wrapper 事实的类别/权限保持 unknown，不能伪判成策略违规或成功。
  原 adapter 与 wrapper 事实可共享调用关联但阶段不同，不是两次业务执行。

未增加 shell 白名单、监督模型调用或成功热路径 Python 进程。

## 验证分层

1. A 独立模块 88 项通过（5.216s）；正常旧/新均绿，仅 scheduler 无交互 lane
   的旧投影红、候选绿。独立复核对照真实 LIFE 生产者字段，确认结构匹配。
2. C 最终 55 项相关回归通过（9.113s），包括真实 shell wrapper、坏桥、依赖
   消失、读/写/未知/伪造恢复、记录器不可写、两 session 观测身份隔离。
   Python 3.10 shim 的 Read/Write 启动竞态已永久化，不能只用 Read 空输出验收。
3. 集成 A/C 及消费者官方隔离验证 **130/130**，18.833s 测试／19.443s 执行器。
   所测 HEAD `a66c24d6d0679d3b3c89429d6ce77f84e99998d2`，无 input drift，
   source bytecode cleanup 前后均 0。记录明确 `full_suite_satisfied=false`。
   run `20261006T032348.974223-ac287ea330d3`，log SHA256
   `896a22ee1317ac42bcd84e5f00d2369deb1455ab587f2b5cba06c34729d24955`。
4. B 真安装器/Hook/recover-only 链，外部 registry/scheduler 使用既有 fixture，
   不是生产宿主。中间 11 项有 3 项失败，原始记录保留；最后只复验实际受影响的
   registry.after_add Read/Write：**2/2**，13.682s，观测记录及旧树精确恢复通过。
   详见 B-ENTRY-REPORT.md。未将旧 11 项改写成最终树全套通过。
   B 所测 `06ab82a` 与集成树在安装器、全部 Codex scripts、窗口测试上 diff 为空。
5. 最终 C 双版本同脚本对照及交叠 AB/BA 共 10 对性能样本，目录
   `20261006T032446.623979Z-wrapper`：median 12.602→13.172ms（+0.570ms）；
   P95 最近秩样本 14.532→13.670ms，在冻结预算内。两对预热排除。
   这是**真实 wrapper + 零退出外部桥夹具**，不是完整生产 runtime 延迟，
   不代表整体安装提速或 Token 收益。此前两次 wrapper 记录只适用于各自源码摘要。

官方凭据本地位于 `.codex-agent/s3c-evidence/formal/`；B 位于其独立工作树
`.codex-agent/s3-c-entry-evidence/`。统一归档由 archive-evidence.py 写入 Optimus
`Sulde/tasks/guardian-unified-plan-20261004/S3-C-repair/<唯一目录>/`，自排除清单
逐文件回读验证。普通测试不覆盖历史归档。

## 过程失败与更正（不隐藏、不混为旧缺陷）

- 旧代码确证：正常输入有效；目录删除后 fallback failed 且缺故障观测；
  symlink→symlink 发布有 unlink 空窗。
- C 中间候选缺陷：local 无 bridge 分支没有观测；坏桥和检查/启动间竞态漏记。
  分别补到永久回归。修复未安装过生产。
- C 中间候选安全缺陷：直接 `python /dev/fd/N` 在系统 3.14 可用，但 venv
  3.10 出现零退出、源码未执行，Write 得空输出。不能称环境噪声或测试问题。
  改为显式 lseek + 有界非空读取 + compile + 要求可调用 main；读取/编译/
  缺入口失败全部非零。原始正式 3 失败日志见 B 报告，未删除。
- 旧静态测试禁止文件任意位置出现 Python -c，误把失败路径等同成功热路径；
  改为真实正常 wrapper + 解释器调用哨兵，断言额外 Python 调用 0，非放松预算。
- B 初次路径比较受 macOS /var 与 /private/var 影响，属于夹具错误；首次官方
  runner 被外层沙盒阻止，提升后才执行，不能把 exit 3 算测试失败或通过。
- `410df0d` 是中间候选，55 项曾失败，不能独立作为交付点；由 `822dbaf`
  修正后才取得上述最终通过证据。部分早期诊断 stdout 仅在会话回执，不伪称
  已有独立落盘日志。最终与正式失败记录均已单独保存。

## 下一阶段决策边界

本机 Codex 0.160.0 的只读帮助未提供已证 keep-cache/atomic-update 入口。
不能推导所有未来宿主都不可能支持，也不能靠 alias 提前发布抵消宿主再次删除。
应先设计缓存外的**宿主注册命令入口**与已有会话的兼容迁移，明确：

- 哪些会话已持有稳定入口，哪些仍持旧路径；无证据不能宣称热迁移完成。
- 宿主仍可 prune 时如何避免触发该窗口，或哪些迁移确需显式会话重载。
- 原权限、摘要/代际校验、回滚边界保持不变；不另建授权系统。
- 获准后才改相应注册/迁移契约，再补未启动旧入口的正负例及全量验收。

本轮无生产安装、远程动作、真实模型调用、push、旧资源删除或历史债务清理；
main/dev 保持原状。U07/U08/U11/Windows 等总纲待办未被本报告关闭。

## 沉淀候选（未入库）

语境：更新时保留入口与故障事实。机制证据 verified；历史一次故障唯一根因
仍 inconclusive。路由正例：区分已启动 FD 与未启动绝对路径；路由反例：升级后
一次成功倒推全过程无中断。执行正例：同一真实窗口同时检查 Read、Write、
故障记录、回滚及解释器差异；执行反例：把空 stdout/exit 0 等同验证逻辑已执行。
