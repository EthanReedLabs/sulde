# S3-C B：安装窗口与别名发布

状态：有界修复候选；完整冻结目标 blocked，不能 accepted/合 dev/安装。
基线：dev eacee0824f8ea0199f780a977e775856c1f6bf32。
B 提交：59b17eb（原子别名与窗口测试）、6c46eaa（真实窗口观测/Write 断言）。
C 最终接入后的所测树：06ab82a6720ad38613185b154257d93ab489dbd4。
本报告是 docs-only，不改变所测源码。协调端只需 cherry-pick 两个 B 提交；
C 原提交已经由协调端持有，不要重复集成相同补丁。

## 已证旧缺陷与范围

1. 真实 installer 的 `registry.after_add` 硬退出点，外部 Codex registry
   fixture 已清理指定旧缓存。此前启动、正在 stdin 边界等待的真实 shell
   Hook 收到 Read 后返回精确 `fallback failed`；正常同输入通过。
   两项合计 11.283s，一正常通过、一目标失败。测试不执行工具 payload。
2. 原 `_publish_retirement_aliases` 在创建新 symlink 前已经 unlink 旧 alias。
   在实际 `Path.symlink_to` 文件系统边界读取旧 identity，确定性 ENOENT。
   改后相同断言通过（0.047s）。

真实 installer、shell wrapper、fallback、observer、recover-only 都执行原代码。
只有外部 Codex registry/scheduler 使用既有 fixture，不能称真实宿主或生产验收。
`SULDE_UPDATE_WINDOW_SOURCE` 可令同一测试断言消费指定基线源码树。

## 最小修复

已存在 symlink 不再先 unlink：在 cache 枚举目录之外创建临时链接，单次
`os.replace` 发布。已存在 alias 若既非旧密封目标也非本次目标，拒绝覆盖。
replace 异常保留旧链接并清理临时链接。record、事务后验、快照恢复仍保留。
非空目录首次转 symlink 不能跨平台原子覆盖，本次没有伪装成原子转换。
不前移 alias、不猜最新运行时、不修改安装权限或重试业务动作。

## 验证与过程更正

- 原子发布正例、replace 异常保留、目标漂移拒绝通过。两个最初失败是
  macOS `/var` 与 `/private/var` 的夹具路径比较错误，双端 resolve 后通过；
  不算产品缺陷。
- 既有 retirement 回归 2/2，通过 10.918s（包含四个硬退出恢复子场景）。
- 首版 B+C 10/10，通过 64.463s，覆盖 registry remove/add、launcher
  before/after、alias before/after、各点 recover-only 精确旧树恢复。
  此版未要求故障观测且未测 Write，不能作为完整通过凭据。
- 强化后的正式 11 项：8 passed / 3 failed，58.859s。两项独立观测缺失，
  一项 Write 空输出；属于 C 候选缺陷，不是旧基线缺陷，也不是夹具失败。
  源码输入无漂移，原日志完整保留。协调端已修复 Python `/dev/fd` 静默空执行
  和局部入口观测遗漏。
- 最终 C 的实际影响路径定向复验：registry.after_add 的 Read 与 Write，
  **2/2 passed**，13.682s，含 telemetry-only、unknown 结果事实和精确旧树
  recover-only 回读。未把之前 11 项改写为最终树全部实跑通过。
- 未跑全量：完整目标已有确定阻断，继续全量不改变该结论。未生产安装。

正式证据位于本工作树 `.codex-agent/s3-c-entry-evidence/`，待协调端统一归档 Optimus：

| run_id | 结果 | log SHA256 |
| --- | --- | --- |
| 20261006T030947.416187-2ea03bd1b1af | 外层沙盒拒绝 sandbox-exec，exit 3，无测试执行 | 8b8fb8f01d6468d32e7eedd1e0234d79eaea2a46155dbeeee24ca9fe5a7baf39 |
| 20261006T031954.986827-ead300678330 | C 中间候选 11 项，3 失败 | b4ec53d7920d4d7bd5e45b371c6a2dc7b18420a519b2165b4e7f41fba6330c7a |
| 20261006T032117.422637-b9c20c65f0f0 | 最终 C 受影响 Read/Write 2 项通过 | e76ae0bc7c46b8f80ce8ac58d6bc0d119f969054c59a10dc2fcade405392a347 |

每份 JSON 绑定命令、源码/环境/runner、开始结束时间、输入前后摘要；未覆盖旧记录。
早期交互测试输出存在当前协调会话，不伪称其已独立归档。

## 完整目标阻断与下一决策

Codex CLI 0.160.0 本机只读帮助表明：`plugin remove` 删除本地缓存；
`plugin add` 没有 keep-cache 或 atomic-update 参数；`marketplace upgrade`
描述为刷新 Git marketplace 快照。这些接口没有提供已证的旧路径连续保留方案。
不是声称所有未来宿主 API 都不可能做到，只是当前范围未找到可验证入口。

一个**尚未启动**的旧会话 Hook 仍可能在宿主删除其绝对路径时得到 ENOENT；
已打开 FD 只能保护已经启动的 wrapper。提前建立 alias 也可能被宿主删除。
本次不能解决这个边界，不得用已启动场景的绿色证明完整连续性。

完整闭环需另行决定：宿主提供保留/原子更新能力，或将未来宿主注册命令迁到
缓存外稳定入口并设计旧会话的可验证迁移边界。不能擅自改宿主配置、替换
registry 权威、猜目录或扩大 fallback 权限。Windows 尚未验收。

未改生产、main/dev、旧权威账本；无模型调用、推送、远程动作、资源清理。

## 沉淀候选

证据 verified：别名原子替换只覆盖 symlink→symlink，不能覆盖宿主先删除
被持有路径；已启动文件描述符与尚未启动绝对路径是不同连续性边界。
路由正例：明确区分两种生命周期后分别验收；路由反例：路径恢复后一次成功
倒推出整个切换窗口无故障。执行正例：真实窗口调用与硬退出恢复配对；执行
反例：只测 Read 空输出、未测 Write 拒绝就宣称 fallback 正常。仅候选未入库。
