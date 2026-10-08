# Guardian Program T32 最终验收

## 控制面投影

- 当前事件头：seq373，`d6c696f6ed819fc44c40ee1821bdfeaeed7773030ea686488ccb1f2b8031c19b`。
- 任务：13 个，其中 accepted 9、superseded 4；没有 planned、ready、running、
  implemented、task_verified、integrated、system_verified 或 blocked 任务。
- findings：78/78 已处置，没有 open finding。
- evidence：100 份任务证据，`--verify-evidence` 为零错误。
- requirements：18/18 均由当前 active requirement traceability 的精确 acceptance
  clause 覆盖。

seq373 后第一次 `final-check` 只报告 8 个刻意尚未登记的 program evidence kind，
没有实现、任务状态、finding、需求覆盖或证据完整性 blocker。本报告为这 8 份总纲证据的
共同说明；最终 ready 仍必须由登记后的独立 `final-check` 决定。

## 总纲证据事实

### failure_injection_suite

- T32 hostile Git matrix 拒绝非 literal add、越界、symlink、外部 repo、amend、
  custom strategy 和未覆盖 merge 参数；拒绝发生在状态变化之前。
- native card 顶层 tamper、过期 installer grant、post-seal runtime 漂移继续 fail closed。
- 当前树额外通过 5 个 installer process-death、rollback-journal、authority drift 和
  partial-cache 用例。

### full_isolated_suite

- clean full clone 执行官方隔离 runner，1370/1370 通过，6 个平台 skip，
  301.396 秒。
- production KB 指向空 sentinel；没有生产写入。
- 最终 `c7fd29a` 只把制品外重复测试恢复到基线，系统测试覆盖的产品字节未变化。

### stage_artifact

- 持久 artifact：
  `/Users/eric/.sulde/artifacts/sulde-0.8.4-0.2.5-codex.20260824145354-ce28ce210c/codex`。
- 官方 stager 输出 577 个文件、366 份知识文档；MANIFEST 与 HISTORY 的 corpus
  SHA-256 同为 `4e3f86d41df4bbc194afe29a7f270d88da51e40197955508022d1dfa532b46ea`。
- artifact 位于持久目录，不依赖临时 full clone 或 worktree。

### installed_generation

- 安装版本：`0.2.5+codex.20260824145354-ce28ce210c`。
- generation：
  `0.2.5+codex.20260824145354-ce28ce210c:51871da47829fc47ec66978207d40e44c4c2df99580c266826753f2c19b52484`。
- stable launcher、installed runtime、executing module root、runtime owner 和 tree
  digest 一致；artifact generation readiness 为 ready。

### scheduler_owner

- provider 为 Codex，runtime owner active。
- launchctl process truth：managed 15、loaded 15、missing 空、failed 空、
  retired_loaded 空。

### live_host_canary

- 当前 session `01a00d6f-65b3-7663-b51b-f88684ffa561` 保持 workspace/task lane
  绑定；prompt/session 使用 verified hot rebind，当前 runtime 的 tool guard/result
  为 live verified。
- 安装后真实 `git -C` add、commit、dev merge 和 main ff-only 已成功；未覆盖的
  merge 语法先被拒绝且没有状态变化。
- doctor status 与 operational readiness 均为 ready；artifact、scheduler、
  interactive、effect 和 native pairing 各域独立通过。

### rollback_evidence

- 当前 main 树的 5 个聚焦 installer 测试在 50.486 秒内全部通过。
- 覆盖 launcher publish 前后进程死亡、rollback journal 恢复、authority alias
  独立性、重算 authority drift 拒绝和 exact artifact partial-cache 恢复。
- 测试只使用临时目录，没有执行生产重装或回滚。

### final_traceability

- WP56-A～G、DERIVED-OWNERSHIP/RESOURCE/JOURNAL/READINESS/DELIVERY/
  ISOLATION/HOTPATH/CRITIC/TIMEOUT/SPLIT 和 PROGRAM-GOVERNANCE 共 18 项全部覆盖。
- T32 对 WP56-D 使用当前安装后的真实 worktree canary；WP56-B、WP56-E、
  DERIVED-CRITIC/SPLIT/TIMEOUT 只在旧完成链、证据文件摘要、accepted 转换和
  当前源码祖先四层核验后重新形成当前事实。
- 旧 fork 事件没有被重放，生产 contract、effect ledger 和 installed cache 没有
  被直接编辑。

## 不扩大范围

- 没有创建 T33 或其他 successor。
- 没有生成第二个 cachebuster、重新安装相同 runtime 或改变 scheduler 定义。
- 没有删除 stash、worktree、旧 cache 或临时验证 clone；清理属于独立可恢复操作，
  不作为完成本 program 的隐含条件。
