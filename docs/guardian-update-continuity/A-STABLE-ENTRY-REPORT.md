# A：缓存外稳定入口候选

2026-10-06；待集成及独立复核，不自行 accepted。未安装生产、未推送。

## 接口与边界

`codex_hook_entry.describe(plugin_root, sulde_root, *, interpreter=None)` 只读；
`prepare` 同签名准备不可变三文件 bundle，返回与 describe 相同的确定性描述。
安装器必须显式传递其已验证 runtime interpreter。`publish(sulde_root, descriptor)`
原子切换 `bin/sulde-codex-hook`；`verify(sulde_root, expected=None)` 回读；
`snapshot_files` 仅列 bootstrap。旧 bundle 保留，不在本模块清理。

包位于 `hook-entry/<bundle_id>/scripts/`，仅含 run-hook.sh、_recovery_defer.py、
_hook_observer.py 原始字节。普通 wrapper 仅添加固定编译 marker，不改策略。
稳定编译形式替换唯一的 pin/path/interpreter 初始化块；不按目录猜新 runtime，
不引入授权。持有经 hash 校验的字节，匿名副本交接给原 wrapper 的专用 FD 8/9，
不接受调用方提供的 helper FD。源路径不会在校验后重新加载为代码。

解释器路径（解析至真实文件）及 SHA 绑定到 bootstrap，运行时在 policy 前
复核摘要；不静默改用 PATH 解释器。此为本地受信解释器故障/漂移检查，不能
宣称可防止被攻击者替换的解释器在自身启动前执行；OS/已验证解释器仍是信任根。

`sulde-hook-entry-complete-v1:` 只在子 wrapper 返回 0 后输出；非零时不转发
partial stdout。输出上限 2 MiB。它是传输完成帧，不是人类授权或业务成功回执。

## 已验证

- 12 项模块测试在 Python 3.10.7（4.268 s）、3.14.6（4.164 s）全部通过。
- 正常入口后删除 cache，尚未启动的稳定入口仍可 Read；Write 仍 deny。
- 坏包、helper/bundle symlink、错 inventory/schema/路径逃逸/摘要身份均拒绝。
- 发布 replace 故障保留旧 pointer；无绑定解释器时 Pre 拒绝，非 Pre 明示盲点。
- PATH 指向系统 Python 3.9 不抢占已绑定解释器。
- 继承 14 个 FD 的真实子进程正常 Read、Write deny；保留槽位防目录/helper 碰撞。
- bridge 内篡改 helper（发生在 loader 校验后）不能改变已持字节的拒绝结果。
- 非零 wrapper 不输出完成帧、也不转发其 partial stdout。
- 组合 status/health/registration/entry 套件 50 项通过；shell -n、diff --check 通过。

## 性能及失败过程保留

运行 `python -B tests/test_codex_stable_hook_entry.py --benchmark`：每轮 2 组暖机、
10 组交叠 A/B，旧命令来自 e9d5405 hooks.posix.json；新命令包括注册层、
bootstrap、真实 wrapper、零返回 bridge。**不是整套 runtime/真实宿主性能。**
P95 以 10 样本 nearest-rank 最大值报告，不隐藏样本。

| 阶段 | Python | 旧 median ms | 新 median ms | 增量 ms | 结果 |
|---|---|---:|---:|---:|---|
| 首版 tempfile/完整导入 | 3.10 | 15.641 | 43.910 | 28.268 | 超预算 |
| -S、精简导入，但 subprocess | 3.10 | 16.219 | 42.915 | 26.695 | 超预算 |
| posix_spawn、有界输出 | 3.10 | 15.502 | 35.182 | 19.681 | 单轮预算内 |
| 同上重复 | 3.10 | 16.528 | 35.722 | 19.194 | 预算内 |
| 同上未优化路径 | 3.14 | 16.956 | 41.329 | 24.373 | 超预算 |
| 固定路径编译、绑定解释器、FD修复 | 3.10 | 16.873 | 34.531 | 17.658 | 预算内 |
| 同最终源码 | 3.14 | 14.070 | 33.259 | 19.189 | 预算内 |

最终 P95 增量为 3.10：17.406 ms；3.14：19.492 ms（50 ms 预算内）。
曾以 importtime 诊断 subprocess 导入累计 4.657 ms，改为 POSIX spawn；
固定绝对 argv0 下的 shell 路径参数展开移除多余 dirname/cd 子进程。
没有取消任何 bundle 摘要检查。集中复核仍应保留重复样本，不能只选低轮。

中间故障：Python repr 字典顺序导致 describe/verify bootstrap 字节不一致，
已用 canonical JSON 归一化；不是旧 dev 缺陷。FD 冲突、旧 Python PATH 和
descriptor 路径完整性也属于本候选集中修复，不冒充已知旧缺陷。

## 未验收

真实 installer 窗口、恢复事务及迁移闸门由 B/协调端集成验收；本 A 不能
凭隔离入口测试声称旧的缓存绝对命令已热迁移。Windows、真实宿主信任面、
生产安装仍未验收。原始本轮输出在子会话工具回执，协调端统一归档 Optimus。

## 最终源码返修补充（4c305e8）

上述性能表与 12 项入口验证属于本次返修前的候选，不代表 4c305e8 的最终性能。
本节补充候选集中复核发现的问题，不将它们归因为旧 dev 缺陷。

- 解释器使用 `-B -I -S`，pinned helper 使用 `-B -I`，隔离业务 cwd/PYTHONPATH。
  同一反例在修复前确实创建模块劫持 marker，修复后 marker 不产生、普通 Write 仍拒绝。
- `verify(expected)` 按密封的旧 descriptor、bootstrap 摘要及 bundle 内容核验，
  不再用新 LOADER 重渲染旧发布件。兼容旧解释器二字段及新三字段形状。
  实际 af51a9f producer 发布的旧件已验证可由新 verifier 接受；永久测试使用
  独立旧格式夹具，只证明兼容核验，不冒充真实旧入口执行。真实双 CLI 升级由 B 验证。
- 新 descriptor 保留解释器调用路径，同时绑定 `real_path` 与内容摘要。
  原 recovery 命令解析比较 resolved 路径，preview argv 则绑定 `sys.executable`
  调用拼写；两者不能混为同一种身份比较。
- 坏 bridge 的 Pre 故障路径先验证受保护 launcher manifest、解释器、runtime
  源码整树及 adapter 摘要，再复用原 resolver/adapter/native recovery 分类。
  无法证明身份即退回原严格 fallback；正常成功热路径不增加整树扫描。
  不执行 repair、不产生新授权，也不依赖坏 launcher 自身健康来验证恢复入口。
- 保留原 `repair_generated_bytecode` 源码身份语义，失败路由的源码摘要按既有
  bytecode 排除规则计算，同时以隔离 pycache prefix 阻止导入未验证 pyc。
  伪造有效时间戳的 launcher_contract.pyc marker 不产生，既有恢复分类仍可抵达。
- POSIX 入口测试明确在 Windows skip，未宣称 Windows 支持。

最终定向测试：Python 3.10.7 下入口模块 **16/16，7.029 秒**；shell 语法和
`git diff --check` 通过。坏 bridge + sealed repair 的同一完整入口反例在
af51a9f 上失败（0.840 秒：旧 wrapper 可 defer，旧 stable 错误 deny），在
4c305e8 上通过；普通 Write、源码漂移仍拒绝，未产生 recovery dispatch。
这是隔离 Pre 分类/交接证据，不是实际 native 审批或恢复执行验收。

编码小门禁已运行但本工作树整体未绿：另六处违规位于
`test_codex_hook_bridge.py:569`、`test_codex_hook_registration.py:40/113`、
`test_codex_update_window.py:59`、`test_hook_observer_continuity.py:65/177`。
本 A 新增 subprocess 文本调用均显式指定 encoding/errors；上述其他所有者文件
未越界修改，交由协调端合并其已准备修复后统一复验。

4c305e8 的集中性能、Python 3.14 复验、真实 installer 窗口仍由协调端/B
统一执行；不以先前低耗时样本代替最终源码测量。未生产安装、推送或自行 accepted。
