# R11 — 兼容性与打包修复公开增量同步完成

日期：2026-09-12。结论：R9/R10 的已验证代码增量已同步到公开 main，远端对象与
本地公开工作树均独立回读通过。本轮不是正式安装，也没有合并 Pro main/dev。

- 公开仓库：`https://github.com/EthanReedLabs/sulde-cc.git`。
- 公开提交：`ca6c123d8c87ed6377e247ceef80ea0bf6edb0d7`。
- 父提交：`9cefc8a3875dafa49de9d95db68e69a74bc56da5`，只增加一个纯公开历史提交。
- Git tree：`14abe89401b67c9bc0651a23c3118379cf987b34`。
- 628 文件：修改 9、保留 619、零增删；清单 `f5c23776…` 与 R10 冻结候选一致。
- 当前会话原生 Allow 已应用 revision 9，receipt `8a9a5251…`。

## 同步内容与边界

增量仅包括精确 Codex CLI 0.154.0 契约、候选安装提前校验版本/执行器身份、Claude
打包排除私有发布工具，以及相应测试和 README。逐项读取了实际 R7→R10 内容 diff；
没有借同步修改功能或扩大文件范围。

正式知识语料及其索引/向量/历史、项目和会话记忆、生产账本与安装回执、内部报告、
私有 Git 历史仍不进入公开树。许可证与旧公开脚手架说明保持原样。R10 已核验的
15 条扫描命中及命中行内容不变；未将 review_only 或 release_ready=false 手改为通过。

## 执行与独立证据

1. 两次读取 GitHub main，确认发布前仍是冻结父提交。
2. 从 GitHub 仅克隆公开 main 历史到任务私有 `publication-002`，建立临时公开任务
   分支；没有复制 Pro 的 `.git` 或把私有任务提交作为父提交。
3. 使用已审核清单机械更新九文件；逐个验证 628 个 Git index blob/模式，形成提交后
   再次检查完整 tree、单一公开父提交及干净工作区。
4. 普通快进 push 精确提交至 `refs/heads/main`，未强推或更新其他远端分支。
5. 从另一份原公开 checkout 独立 fetch main，回读全部 628 文件、blob 摘要和模式；
   在本地工作区内容/路径安全且干净时，只快进本地公开 main。
6. 再次检查本地 HEAD=origin/main=公开提交、工作树 clean、全部 628 文件匹配。

完整凭据：[R11-publication-result.json](R11-publication-result.json)。机械准备与只读
检查脚本：[r11-publication.py](r11-publication.py)，不包含网络或推送执行器。
四份私有证据位于 `.sulde/public-export/r11-*.json`，摘要已固定在结果文件中。

## 测试复用及未覆盖范围

本轮重新回读 R10 的 44 项定向回归、39 项公开候选测试与独立包比对记录摘要，均与
R10 报告一致；R9 真实候选验证 summary 摘要也保持不变。发布快照就是原已验候选，
没有重跑全量或重装。R10 两平台 Codex 包与 R9 字节/模式相同的结论继续有效。

不因此新增任何安装 receipt，不把旧证据改称本轮新跑的验收。候选人工审批界面、
真实 scheduler、升级回滚和 Windows 原生执行仍未覆盖；生产业务历史 Hook 报错
也不能被本轮代码同步宣告修复。

## 保留状态与执行复盘

- Pro main=`bd216b3…`、dev=`e61683c…` 未变；main 三项既有 `.ua` 修改保留。
- 没有安装、cachebuster、marketplace 修改、正式 KB/记忆写入或私有远端 push。
- 合同回读 revision 9 active；pending proposal、pending verification、open event、
  integrity breach 均为 0。实际 Git 结果由远端对象核验，而非控制面回执替代。
- 原生提案输出包含非 JSON 前缀，Agent 第一次直接解析失败；回读确认提案已经创建，
  没有重复创建。预览合同锁的一次沙盒限制通过正常宿主权限重试解决。
- 原生批准未传 prefix_rule，宿主仍报告保存精确前缀；根因继续 inconclusive，
  不作为未来权限，不在本轮修改宿主配置。
- 任务续接/Intent Guardian 用于公开范围确认；知识库范围冻结规则用于复用已通过
  证据、避免再扩展测试。当前任务未合入 Pro dev，故保留 Pro worktree。临时公开
  clone 与历史发布 clone 留在私有证据目录，未自动清理审计材料。

停止线已达到：本次公开代码增量已交付。后续正式安装与 Pro 集成需独立明确范围，
不把“继续同步”自动解释为部署授权。
