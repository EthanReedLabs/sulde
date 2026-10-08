# S3-C 安装后问题分类与诊断

capability_tier: deep

日期：2026-10-05。基线/生产安装源码c325c7c，当前dev eacee08（后继仅报告）。
revision9批准只读诊断、隔离夹具和任务文档，不批准产品修复或重新安装。
回执9db909f974bfa52f99c3cec48ffe962fd639630c24e264ff08194cfa270bf58b。

## 分类结果

| 观察 | 已证事实 | 分类/处置 |
| --- | --- | --- |
| LIFE global degraded | 13:53:04Z状态L2/L3/L4/evolution ready，五维与持久回读全部true；scheduler scope ready；缺当前人类lane导致overall false | 保护语义不是调度缺陷，不给后台伪造人类身份 |
| MCP仅给背景degraded总灯 | read_life只取global life_status，statusline_healthy据此翻黄，不保留导致降级的scope；受控配对复现 | 状态投影/可解释性需修，不把所有degraded直接改绿 |
| 一次fallback failed | 上轮ps工具未执行；随后安装完成、同session双身份负例和doctor通过 | 安装期可用性现象已证；原始低层stderr缺失，唯一现场根因inconclusive |
| 故障时Read也被拒且无记录 | 真run-hook.sh外部桥边界触发静态scripts移走；fallback和observer均失去依赖，输出同类错误且无独立记录 | 可复现的共享故障域，需独立可达的入口/观察；不是正常业务策略拒绝 |
| 故障时ps被拒 | 静态依赖完整时，bridge失败后Read放行、ps保守deny（不是fallback failed） | 既有fallback支持范围；不能宣称任意只读shell均支持，也不因本事故增加通用shell豁免 |
| doctor hook_failures clear | 当前observer数据库最早行13:53:04.196579Z；13:49–13:54窗口31 normal、1 policy_rejection；没有覆盖先前现场的故障原文 | coverage缺口，不证明故障从未发生/从未登记/被安装删除 |

## 代码链与因果边界

`scripts/kb/life-cycle.py:build/closed_loop_projection`保留全局交互授权门；
`scheduler_execution_succeeded`已独立判断后台执行成功。
`scripts/kb/sulde-status.py:read_life/statusline_healthy`没有把相同scope分层
带给背景状态输出。`sulde_status_snapshot.py`将有界快照送MCP；三小时TTL下
本轮age3211s仍fresh是既有定义，不等于即时观测。不得通过强跑后台任务把
缺陷掩盖为短时绿色，也不得把传输成功解释为业务状态全绿。

`run-hook.sh:run_pre_tool_fallback`依赖同一SCRIPT_DIR的pre-tool-use.py；
桥异常路径又从同目录调用_hook_observer.py。若旧目录不可达，两条失败路径
同时失效；Pre最后输出固定deny正确保护未知物质操作，但诊断可用性/故障
证据丢失。`install_codex_plugin.py`顺序为publish retirement targets→
registry remove/add→launcher publish→smoke→publish aliases；末次alias发布
还有unlink/rmtree→symlink窗口。这些是潜在失效边界，尚未用真实安装failpoint
证明哪一个导致历史ps失败，不能只凭时间相邻宣称根因已完全定位。

## 有效对照与证据

脚本：`diagnose-window.py`；只在任务.tmp里创建夹具并移动其scripts，未改
生产目录、未执行payload中的命令、未改classifier或替换其返回值。
外部桥是故障桩，不能当成正式launcher/完整installer验收。

1. 正常桥+Read：无deny。
2. 非零桥+静态依赖完整+Read：无deny，有独立非零退出观测。
3. 相同桥故障+ps：保守deny；不是fallbackfailed。
4. 桥执行期间移走临时scripts+Read：精确fallbackfailed，observer无行。
5. 相同失效+写入payload：仍deny，不放宽安全边界。
6. 真实statusline_healthy正常状态true；仅把life_status设为degraded→false。
   这证明输出选择规则；实际degraded来源另外由只读life文件证实。

全部断言通过，模型调用0，无全量/模块重跑（无产品代码变化）。
Optimus：S3-C/20261005T145236.373856Z-diagnostic.json；
SHA256 7a5199a74f11dc1574edda08da5d6001820f5e7100a5b856db28447f3180b177。
含五场景stdout/stderr/退出码/观测行、源码和夹具摘要、生产life只读选定字段。
旧/新产品代码对照尚未做：本轮没有修复候选，不称“旧红新绿”。

集中独立只读复核通过：证据文件重hash相符、五组夹具的三个关键脚本与源码
逐字节一致；正常/故障配对有效。`payload_executed=false`来自夹具从不运行
业务命令的设计，不是宿主执行器的非执行证明；实际宿主证据仍引用S3-B。
修复任务不能以本轮桩对照替代真实installer切换链，也不能将现场唯一原因
从inconclusive升级。审核未运行额外测试、模型调用或修改账本。

## 接续与停止线

后续统一修复任务见S3-C-REPAIR-TASK.md，先独立审查本诊断。真实Claude会话、
U07模型行为、U08活动升级回滚、Windows、U03远程业务效应仍各自保留。
本轮没有修改生产规则、恢复历史债务、重启会话、更新安装、推送或清理资源。

## 沉淀候选

语境：热更新发生时入口与故障记录器可能共享失效路径。机制证据verified，
历史唯一因果inconclusive。路由正例：故障期对照入口/记录器可达性；路由
反例：later doctor clear当作没有发生故障。执行正例：保留实际失败并用
配对注入区分策略deny和基础设施deny；执行反例：为获得绿色扩大只读shell
名单、取消物质保护或把后台scope伪装成人类lane。仅候选，不入正式知识库。
