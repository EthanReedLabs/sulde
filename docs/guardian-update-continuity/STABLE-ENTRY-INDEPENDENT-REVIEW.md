# 稳定入口独立复核（源码范围）

复核者 `/root/update_review`，只读，没有实现写入。实际源码 HEAD：
`e33fb2246adbcf96cb84c7e6070057bb18e75034`。

结论：本轮修复范围内通过；不是生产安装或旧会话迁移的验收。

## 实际检查

相同精确 Python 3.10.7、相同 sealed recovery payload 下，原 `run-hook.sh`
和新的六事件实际注册命令均 exit 0、空输出；普通 Write 输出结构化 deny。
`recovery_dispatch_started=[]`，未执行恢复，不把 Pre defer 当成人工授权。

独立执行以下四项，4/4 通过，2.605 秒：

- `test_sealed_native_recovery_route_survives_broken_bridge`
- `test_sealed_bytecode_recovery_does_not_import_unverified_pyc`
- `test_project_modules_cannot_execute_in_bootstrap_or_pinned_helpers`
- `test_new_verifier_accepts_old_sealed_bootstrap_without_rerendering`

代码确认：恢复前校验现役 runtime、代际、解释器及 adapter 后复用原路由；
无新增授权层。有效但未验证的 pyc 不导入；解释器调用 alias 保留且绑定真实
目标摘要。旧 bootstrap 有 sealed expected 时比较原身份，不以新代码重渲染。
整树扫描仅在桥失败后的恢复路径，正常成功路径未增加该扫描。

安装器与注册层此前集中复核已确认：严格 JSON registry、fresh 残留拒绝、
发布后移到最终准入之后；完成帧及 matcher / async / timeout 约束成立。
工作树与 diff --check 均干净。

## 限制

尚未验证真实宿主 PermissionRequest、人工确认后的实际 repair、生产升级。
四项测试中的旧 bootstrap 是冻结旧 wire-shape 夹具，不代替 B 的真实安装器
跨源码升级用例。legacy 旧命令迁移限制继续保留，不据此宣布可以 prune 现有
旧会话依赖的目录。正式集成回归与最终性能由协调端记录，未包含在本结论中。

## 最终候选消费者窄复核

实际 HEAD `027b486ef380be5dff24768eaeba5a44f9876b6c`（A 分支，已集成）。
首次复核发现 bin symlink 在后续校验前已触发 writer，阻断交付。修正后 reviewer
独立复跑八场景与正常配对，2 项 / 0.081 秒通过；旧临时越界反例变为
writer_called=false、escaped_marker=false，链接保留，外部目录未变。

确认：bin/hook-entry 检查在首次写入前；生产安装器未改；八 native 消费者只
调整初始化，不降低最终断言。B 仅补协议输入与精确 AST 演化，原 golden 保留。
窄复核没有重跑 15 native；协调端随后在统一分支的正式 70 项补测重新覆盖全部
消费者。此结论不代表生产安装授权、旧会话迁移或整体 accepted。
