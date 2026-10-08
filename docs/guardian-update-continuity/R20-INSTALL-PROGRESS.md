# r20 双宿主安装执行记录

目标仍为 Sulde 在 Codex 和 Claude Code 两侧安装并真实验收，不以候选通过代替。
当前会话 r20 原生方案已 applied；本阶段 L0/L1/L2 与通过门后的 dev 合入获准，
正式安装、版本密封动作、宿主停止须另获精确维护批准。预算 120 活跃分钟。
计划：LAYERED-ACCEPTANCE-TASK.md。起点 21f63ab，dev 3012363，main f932ca8。

只读现状：Codex CLI 0.160.0，Sulde 0.2.5+codex.20261005134315-d918c7a2ed；
Claude Code 2.1.282，sulde-cc 0.8.10，两者 installed/enabled。Claude marketplace
已指向版本化 artifact，不再是历史 main checkout。源码版本与已装版本相同，
真实发布前需唯一版本，不能直接覆盖同版本缓存。Python 3.10.7 + PyYAML 6.0.3。

本地 candidate 源码检查：prepare 只 stage 并读取生产 CAS；verify 使用独立
HOME/CODEX_HOME/SULDE_HOME/launchagents，清除继承合同/凭据环境，用真实 CLI、
Hook、MCP 和真实 PreTool 链。scheduler 仅 fake launchctl + dry-run；其结果不证明
真实 launchd。native_permission_ui 与 scheduler_host 由正式收据明确标 unobserved。
本轮 helper 不设置 SULDE_ISOLATED_TEST_RUN_ID，不跳过自身 OS 隔离证明。
Claude 本阶段为官方 staging 与 CLI validate；真实安装与 live hooks 仍待 L3。

执行顺序：读取并映射旧证据 → 实际隔离 candidate prepare/verify → Claude staging /
validate → 处理必要最小缺陷 → 冻结版本与集成输入 → 发布全量和集中复核 → 获准 dev
合入 → 绑定两侧精确安装/回滚/维护窗口 → 正式安装与真实宿主正反验收。
不扩建系统账户/GUI/VM，不复制认证，不调用付费模型，不改 main，不 push。

本地记录：`.codex-agent/layered-r20/<run-id>/`；阶段结束归档 Optimus 同任务目录。
每次阶段输出先保留 stdout/stderr/result，再判断成功。当前不宣称任何新安装完成。

夹具更正：首次 prepare 正确拒绝未提交源树。一次组合命令的 Git 提交受外层
沙盒限制失败，后续命令仍执行并再次碰到同一前置；已改为确认提交成功再启动。
正式构建在 7e3cd5f 用 2.295s 完成，verify 15.467s 失败：普通写入探针位于
`.codex-agent` 祖先下，被控制工件保护正确拒绝。执行候选改为已批准的独立
`/private/tmp/sulde-s3c-r20-<run-id>`；不放松守卫，不伪装产品修复。
失败记录保留在 20261007T094549.969410Z、20261007T094605.863853Z、
20261007T095345.462788Z；生产文件摘要前后相等。

参考：本地实际 CLI 帮助和安装器是本机接口依据；
[OpenAI 插件官方说明](https://developers.openai.com/plugins/build/plugins)
用于核对本地市场与配置边界，不据网页替代本机精确 CLI 契约。
知识库 ap-0185 原文提示检查重复注册；不得据此盲删现有 Hook 字段。

## 2026-10-07 完成证据与新增阻断

cab332a 的隔离批次 20261007T095529.725857Z 完成：Codex prepare 1.972s、
verify 21.560s；真实 CLI app-server/unified-exec 的正例执行、破坏性负例
动作前 deny、marker absent 和两种代际身份均有凭据。维护人审界面和真实
scheduler 为 unobserved；不是生产通过。Claude staging 850 files，初次
marketplace validate 通过；补充显式 plugin.json 的 strict validate 通过，
850 文件摘要前后相同，树摘要 a5411c891088c063f512d5aa5c92ed0b4c32e47ad8df77c49fe0422fd7417fb4。
其补充身份记录为 claude-identity-20261007T100741.846920Z.json。

Optimus 独立归档 r20-layered-20261007T100808.658528Z，21 个文件逐一回读一致，
manifest SHA256 450570b62d753aae7526b6f68f76ea43f1b5e5cec94338116cdc2757398df77c。
前一 19 文件归档保留，未覆盖。四项生产文件摘要相同仅覆盖所列四项，不冒充
完整生产写入审计。生产 uid501 当前 managername=Aqua 且 life-cycle label
可见、last exit=0；旧 uid502 的 GUI 缺口不外推到生产，亦不是新代际验收。

官方全量 20261007T100012.047721-f478d839af10：HEAD cab332a0117a95d394df6a1d9d8a7d009887308c，
2981 项中 2952 通过、29 skipped，零失败，exit=0，input_drift=false，2361.679s。
日志 SHA256 963590947915e223be10f36d2eaa5203b5f23f64068e708ef50518c412f20b8e。
源码树在整个运行期间保持未变；后续修复不得冒用此 exact-tree 结果。

集中独立复核确认新增 L3 阻断：recover-only 对 committed 只验证新代际；
普通安装明确禁止 stable lineage 降至 legacy；现有入口不能满足分层计划
第 6 节承诺的“提交后恢复精确旧代际”。旧文件保留不等于恢复入口存在。
这是缺失能力/方案错误，不是环境等待或全量失败。原承诺由此明确更正，
不改写旧记录。生产尚未改变，两侧版本尚未刷新，未合入 dev/main、未 push。

当前会话原生批准 r21（receipt 0950be2ee97b4a94c592d7e68198aca595685c8eca8a3b350456137b125b9871），
仅授权 R21-REVERSAL-TASK.md 的源码设计/开发和隔离验收，正式安装仍需精确
维护批准。新逆向事务不能改写原 committed journal，不能提供通用强制降级。

全量日志补充归档：`r20-layered-20261007T104044.800222Z`，23 个文件，
manifest SHA256 `1f52936b75ef622c91de690741313dde3ef78ef1263a9697ce3c2e1c20d70a24`。
包括上述 L1 工件记录和已结束的 cab332a 全量 JSON/log，均已独立回读。
归档 helper stdout 的 `L1-only-not-installed` 是旧范围标签；本归档实际覆盖
L1 + cab332a L2 全量，不覆盖 r21 源码或任何正式安装。保留旧输出并在此更正。
