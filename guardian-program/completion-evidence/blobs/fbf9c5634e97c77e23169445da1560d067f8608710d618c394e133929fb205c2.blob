# T30 packaged KB aging provenance

## 结果

✅ 完成检查：`python3 -m unittest tests.test_knowledge_history tests.test_kb_aging tests.test_stage_plugin tests.test_codex_plugin_install`，worker 与协调端独立复跑均 exit 0；59 个 scoped tests 全部通过，1 个平台条件用例跳过，耗时分别为 148.223 秒与 112.930 秒。测试覆盖源码 Git 年龄、无 `.git` packaged runtime、缺失/篡改/错 corpus fail closed、官方 Claude/Codex staging 和 installer 验证。

✅ 完成检查：两次独立 `stage_plugin.py --target codex --platform posix` 均 exit 0，各自验证 366 个 corpus documents；两份 `knowledge/HISTORY.json` 字节完全相同，SHA-256 为 `9dc26010a60a91cb2aba96d5fc20f5ecc5afd6053952c9d5b8aef2755c8527fb`，两份 runtime tree digest 均为 `29487f1750ff949c6dd5a0ddadd2d1389acd185e0d6803387e4300cef03029d9`。staged runtime 不含 `.git`，其真实 `kb-aging.py --dry-run` exit 0 并报告 `documents: 366`。

✅ 集成纠正后，原 scoped modules 加 `test_stage_release_inventory` 共 67 个 tests 全部通过，1 个平台条件用例跳过，耗时 113.458 秒；真实 `.git` full clone 中上一轮失败分组共 68 个 tests 全部通过，1 个平台条件用例跳过，耗时 10.402 秒。

实现结果：只修改任务定义中的 provenance、aging、stager、installer、四个测试路径、Codex cachebuster 和本报告；没有写生产 contract/ledger、installed cache、LaunchAgent、远端或外部项目，也没有执行生产安装、scheduler kickstart 或 live session 操作。

## 过程

- 新增 `tools/kb-index/knowledge_history.py`：从已验证 corpus manifest 和源码 Git 历史生成严格 schema，记录精确路径、文档哈希、带时区秒级提交时间、corpus SHA 和 canonical self digest。
- 将最初逐文档 366 次 `git log` 改为单次批量只读 `git log --name-only -z`，保留每个当前路径的最近一次提交时间，并用同一文件的两次不同时区提交锁定“最新命中”语义。测试断言每次 history build 只启动一个 Git 进程。
- `kb-aging.py` 在真实 checkout 中继续使用原有 Git 路径；只有 `.git` 不存在时才要求并加载已验证的 packaged history，禁止 mtime 或开发 checkout fallback。
- Claude 与 Codex stager 在 generation 封印前生成并立即回读验证 `HISTORY.json`；Codex runtime tree digest 因而覆盖 provenance 文件。
- installer 把 `HISTORY.json` 纳入必需文件，并在接受 staged artifact 前验证 schema、自摘要、corpus、路径与内容哈希绑定。
- 源码实现级门通过后才把 Codex plugin version 更新为 `0.2.5+codex.20260824123238`。

## 遇到的问题

- 初版对每篇文档单独调用 `git log`，59-test scoped suite 用时 463.001 秒，重复 staging 在完整回归中不可落地；批量实现后同一 59-test 套件降至 148.223 秒，12 个 history/aging/双 staging 用例降至 2.926 秒。
- worker 内调用官方 `run-isolated-tests.py` 时，第一次因 audit cursor 默认目录不在 owned-path 沙箱内而未进入测试；将 cursor 指向授权 scratch 后，runner 的嵌套 `sandbox-exec` 又被外层原生 Seatbelt 拒绝。两次都是 isolation bootstrap fail closed，不是测试用例失败。
- 直接在 worker 单层沙箱运行全仓 discovery 产生大量依赖真实 Git remote、host provenance 和写路径的环境假阴性，随后在重复 staging 中被中断；该结果没有计入通过证据，完整官方隔离套件保留给协调端。
- 首次 L3 执行在 1800 秒硬超时前完成最终 59-test，但尚未写报告，因此 runtime 正确判为 FAIL。续跑收尾又因宿主 Codex CLI 在任务期间从 audited `0.149.0` 升为 `0.149.1` 而在 provider 启动前 fail closed。本报告由协调端基于 append-only worker events 和可复核工作区结果补齐，不把任一失败终态冒充为 worker success。
- 首次从 linked `dev` worktree 运行 1362-test 官方套件得到 14 failures、13 errors；full-clone 校准证明其中 broker/launcher 的 25 项是错误测试拓扑造成的假阴性，剩余两个 release-inventory failure 是 `F30-001` 真实集成漏项，另一个是当前宿主 `0.149.1` 与已审计 `0.149.0` 的真实系统阻断。
- `F30-001` 的根因是 worker 为了让尚未提交的新模块参与 staging，临时把 `tools/kb-index/knowledge_history.py` 放入只面向显式未跟踪 `scripts/kb` 模块的 legacy inventory；该文件提交后已由受 Git 跟踪的 `tools/kb-index/` runtime prefix 打包，临时条目反而破坏授权摘要和扁平 import 断言。

## 解决方式

- 保留稳定 Git commit 时间为唯一年龄来源，只把运行时所需的最小历史投影作为构建产物；不复制 `.git`，不把 actor 指回 source checkout，不使用文件 mtime。
- 使用内层 canonical digest 检出 payload 意外篡改，以 corpus SHA 和逐文档 path/hash 验证内容绑定，再由 Codex delivery generation 提供外层不可变树封印。
- 将批量 Git 输出解析做成严格 fail-closed：缺少提交元数据、缺少任一 corpus 文档、非 ASCII timestamp、无时区、重复/碰撞/乱序和 corpus 漂移全部拒绝。
- 对 worker isolation 限制只披露并移交协调端，没有修改 runner、放宽 owned paths 或把 direct discovery 假阴性写成通过。
- 对 `0.149.1` 宿主漂移保持现有 installed authority fail closed；T30 不拥有 native runtime authority 路径，因此不越界修改或降级 Codex CLI。
- 对 `F30-001` 删除已失效的临时 inventory 条目，并新增回归断言：history 模块必须由 Git 跟踪入口进入产物，不能伪装成 legacy 未跟踪 runtime input。定向 3/3、扩展 67/67 和 full-clone 集成 68/68 均通过。

## 遗留风险与建议

- 协调端仍需在候选合并到 `dev` 后运行官方 OS-isolated full suite；在该证据通过前不得进入 `main`。
- 当前 installed Sulde authority 精确审计 `codex-cli 0.149.0`，而宿主现为 `0.149.1`。这不是 T30 owned scope；必须先经独立、明确批准的宿主兼容修复重新审计 help/profile/broker 合约，才能执行官方安装和 15/15 scheduler 验收。禁止手工降级、改 symlink、改 installed authority 或放宽为未经测试的版本范围。
- 真实 full clone 的宿主校准组为 68/69，通过 68；唯一失败是 `test_installed_codex_0149_real_cli_contract` 观测到 `codex-cli 0.149.1`。因此不再把 linked-worktree 的派生失败列为产品 blocker，也不把该 68/69 写成完整套件通过。
- 因此本报告不声称生产安装、`com.sulde.kb-aging` 当前退出零、scheduler 15/15、post-install live session 或程序 final-check 已完成。
- T30 的 source candidate 本身没有额外功能或任务拆分；协调端应先完成代码审查和 `dev` 验证，再向用户报告唯一外部宿主 blocker。

## 沉淀候选

### Layer1 问题卡：运行时隐式依赖 VCS 历史

- **问题类型**：release-topology mismatch / bug-fix
- **问题语境**：源码测试在 Git checkout 中运行，生产 scheduler 却从不含 `.git` 的不可变 artifact 启动；actor 运行时调用 `git ls-files`/`git log`。
- **已确认根因**：构建合约只封装了知识内容 manifest，没有封装 aging 所需的最小历史 provenance，导致源码态绿色而安装态必然 exit 2。
- **证据状态**：verified。旧 installed runtime 默认 dry-run 报 `not a git repository`；新 staged runtime 无 `.git` 仍 exit 0 并分析 366 篇文档，缺失/篡改/错 corpus 用例均 exit 2。
- **路由正例**：生产 artifact 不含 VCS，但运行逻辑需要稳定提交时间，应在构建期生成 corpus-bound provenance。
- **路由反例**：运行逻辑只需要 artifact 静态内容且已在同一无 VCS 拓扑测试，不需要历史投影。
- **执行合格例**：构建期单次批量读取 Git，严格验证并在 generation 前封装；安装态只读已封印凭据。
- **执行失败例**：把 LaunchAgent 指向开发 checkout、复制整个 `.git`、使用 mtime，或逐文件 fork 数百次导致发布测试不可落地。
- **建议容器**：anti-patterns。

### Layer1 问题卡：精确宿主审计被补丁升级阻断

- **问题类型**：host-version drift / design-decision
- **问题语境**：长任务启动时 Codex CLI 与 installed authority 均为 0.149.0，任务期间全局 CLI 更新到 0.149.1；后续同任务续跑在 provider 启动前被精确版本门拒绝。
- **已确认根因**：版本与 help/profile/broker 观测被封装为一个 installation-time authority；外部包管理器更新可执行文件后，旧 generation 不再拥有当前宿主执行权。
- **证据状态**：verified。当前 `codex --version` 为 `codex-cli 0.149.1`，deployment descriptor 仍记录 `codex-cli 0.149.0`，agent runtime 明确报版本不等。
- **路由正例**：宿主二进制发生变化，应重新审计并发布新 authority generation。
- **路由反例**：仅任务模型/推理档改变但 executable bytes 与 help contract 未变，不属于二进制 authority 漂移。
- **执行合格例**：冻结新版本、重跑真实 help/profile/broker probes、更新源码测试并通过官方安装链切换 generation。
- **执行失败例**：直接改 production descriptor、把 exact check 放宽为任意 patch、临时改 symlink 或无回归地降级全局 CLI。
- **建议容器**：anti-patterns。
