---
name: kb-search
description: 检索 sulde 知识库(反模式/案例研究/平台KB/技术文档/工作模型)。调试报错或异常行为、规划实现方案、怀疑踩到已知坑、需要平台特定经验(android/ios/flutter/harmonyos)时使用。用症状描述查询,支持容器与平台过滤。
---

# KB 检索(契约 kb.search 的 skill 实现)

按 T1.5 → T1 降级执行,出参形状一致(见 `docs/kb-retrieval-contract.md` §3)。

## T1.5 主路径(本地混合索引)

先使用当前全局 Sulde 规则给出的 `kb-index` 命令；没有规则块时使用 bootstrap 生成的
宿主中立稳定入口：

```bash
SULDE_KB_INDEX="${SULDE_HOME:-$HOME/.sulde}/bin/kb-index"
"$SULDE_KB_INDEX" search "<症状式查询>" -k 5 --json
```

- 查询写**症状/现象**,不要只写术语(混合检索同时吃词法与语义)
- 可选过滤:`--container anti-patterns|platform-kb|tech-docs|case-studies|work-model`、
  `--platform android|ios|flutter|harmonyos|web|cross`(platform 过滤自动含 cross)
- 可选目的:`--purpose route|recall|solution|all`。自动判断是否应用知识时用 `route`，
  只让显式 apply/skip 样本竞争；默认 `recall` 用于宽诊断，需要具体解法/验收样本时用
  `solution`
- 出参增加 `role, applicability, problem_type, evidence_status`：
  - `applicability=apply` 才可作为当前任务建议；
  - `skip` 表示命中的是路由反例，**不得应用该条规则**；
  - `inconclusive` 只能作为继续收证据的线索，不得升级为强制结论
- v2 的辅助普通章节仅在 `purpose=all` 中出现；`route/recall/solution` 只让显式语义
  角色竞争，避免一般说明压过 `skip/fail`。旧文档仍以 `general` 兼容参与

## T1 降级(exit 2 = 索引未构建)

读当前 Sulde 源码/发布运行时中的 `knowledge/INDEX.md`(编号+标题+平台的全量目录),
自行做语义匹配挑出候选,必要时辅以对 `knowledge/` 的 grep。

(索引可用 `"${SULDE_HOME:-$HOME/.sulde}/bin/kb-index" build` 构建；稳定入口不存在时先运行
当前发布件的 `scripts/kb/bootstrap.sh --host claude|codex`。构建失败不阻塞,继续走 T1。)

## 铁律

- **检索结果只是线索**:采纳任何结论前,必须 Read 命中项的 `source_path` 原文全文——
  向量库不是内容真源,excerpt 不足以作为行动依据
- Read 后对照“适用边界 + 路由正反例”再决定是否采用；对照“执行正反例”验收产物
- 命中反模式时,在实现中主动规避其 ❌ 做法并遵循 ✅ 做法
- 查不到不代表没有:换一种症状表述再试一次,仍无则如实说明未命中
