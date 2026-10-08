---
doc_id: work-model/git-worktree-content-evidence-materialization
container: work-model
platform: cross
summary: 多 worktree 与隔离发布验证必须把工作树、index、提交树、文件模式和引用形状分别证明，不能用另一个 checkout 的状态代替。
related: [ap-0244, ap-0192, work-model/verify-build]
sedimentation_schema: 2
problem_type: workflow
evidence_status: verified
---

# Git 多工作树的内容证据与检出后物化

## 问题原型

同一仓库存在主工作树、任务 worktree 和隔离发布 clone。文件在某个目录里已修改，另一个 worktree
执行了 commit，报告便声称修改已提交；或测试只在瘦 clone 中失败，就被当成产品回归。普通文件
权限又被误认为可由 Git 保存，导致不可变 evidence 检出后仍是可写状态。

## 根因与证据

根因是把四种事实压成“Git 已完成”：工作树字节、index 内容、commit tree 对象和检出后的文件系统
属性。它们属于不同资源。已验证证据包括：在错误 worktree 提交不会包含目标文件；Git 普通模式只
保存 executable bit，不能保存 0400；隔离 clone 缺少任务依赖的 refs 会在测试体前 setup 失败；
兄弟 worktree 中的 fixture 被清理后回归失效。逐层读回 tree 对象、引用形状和文件身份可稳定区分。

## 适用边界

- 多工作树、发布 clone、内容寻址 fixture 或只读 evidence 进入提交时启用。
- 单一干净仓库中的普通源码编辑仍应核对 index/commit，但不需要完整多 worktree 关系图。
- 环境 setup 失败不是产品 PASS，也不是业务 FAIL；修复引用/fixture 后必须完整重跑。
- 0400/0700 是检出后物化属性，不能写成 Git tree 的可移植事实。

## 判定样本

### 路由正例

- **输入**：报告称证据已提交，但修改位于另一个 worktree；或 fresh clone 找不到历史 fixture/分支。
- **预期**：apply
- **原因**：需要区分工作树、index、tree 与 clone 引用形状。
- **来源**：observed

### 路由反例

- **输入**：单仓只读查看某个已知 commit 的源码，不涉及检出后权限或外部 fixture。
- **预期**：skip
- **原因**：直接读取 tree object 已足够，不需要完整物化流程。
- **来源**：constructed

### 执行合格例

- **做法或输出**：记录目标 worktree 根和 common-dir；核对目标 index；用 commit tree 读回确切文件
  摘要；fresh clone 具备声明 refs 和仓内 fixture；检出后验证内容/inode，再物化 0400/0700。
- **预期**：pass
- **原因**：每种事实由对应权威来源证明。
- **来源**：observed

### 执行失败例

- **做法或输出**：只看 `git status` 干净就声称其他 worktree 的文件已提交，或把 `chmod 0400`
  后的工作树状态当成提交可恢复属性。
- **预期**：fail
- **原因**：状态来自错误资源，fresh clone 无法重现。
- **来源**：constructed

## 正确做法

1. 任务开始固定 repository identity、worktree root、common-dir、branch 与 base commit。
2. 暂存后逐文件核对 index；提交后从目标 commit tree 读回字节，不以当前目录状态替代。
3. 发布 clone 预检所需本地/远端 refs、submodule/fixture 和对象可达性；setup 失败先修环境再全量重跑。
4. 历史 evidence/fixture 进入仓库并绑定 SHA-256，不依赖兄弟 worktree 或机器残留。
5. 内容和 inode 安全检查通过后，由确定性工具物化普通文件 0400、目录 0700，并再次只读验收。

## 执行流程

`freeze identity → inspect worktree bytes → inspect index → commit → read commit tree → fresh clone →
materialize permissions → verify`。任一步失败都保留前一层事实，不越级宣告提交或发布通过。

## 验收与失败处理

tree 摘要、引用集合、fixture 摘要和文件系统模式必须分别列出。环境缺失判 `setup_error`；内容漂移
判 `integrity_blocked`；仅权限未物化判 `materialization_pending`。

## 消费与防复发

任务模板、Git 资源适配器、发布预检、fixture loader 和安装器共同消费。回归覆盖错误 worktree、
共享 common-dir 替换、瘦 clone、缺 ref、兄弟目录消失、同内容不同 inode 和权限重建。
