# 知识库检索标准契约（KB Retrieval Contract v1）

> 状态:收敛稿(2026-07-28 更新:定稿三项运行决策——注入三闸、双引擎按数据面分工、
> SessionStart 索引保鲜;并纠正"cognee 无 BM25"的早期判断,引入 T1.5 本地混合索引层)。
> 定位:**契约先于引擎**。本文档定义知识库检索的文档 schema、查询接口与写入规则,
> 与具体向量引擎无关。当前实现后端为自建 cognee(A1),未来可替换为任意向量库,
> 消费方(skill / 未来 MCP 服务)只依赖本契约,不依赖引擎内部结构。

## 0. 设计原则:数据顶尖,引擎可选(渐进增强)

cognee 是工具不是依赖。价值排序:**沉淀数据本身 > 检索契约 > 任何引擎**。
能力分四级,低级永远不依赖高级:

| 级 | 依赖 | 能力 | 角色 |
|---|---|---|---|
| **T0 数据自描述** | 无(有 git 即可) | frontmatter 元数据 + 固定小节 + INDEX.md,人和 agent 直接读 | 真源 |
| **T1 目录检索** | 零构建 | agent 读 INDEX.md 语义匹配 + grep | 保底 |
| **T1.5 本地混合索引** | 本地构建,无服务 | BM25(FTS5+中文分词)+ 向量(bge-small-zh)加权融合,受控词过滤 | **KB 检索主力** |
| **T2 cognee 增强** | cognee 服务在场 | `kb.related` 图关系、跨机会话记忆、TEMPORAL 时间查询 | 增强件 |

约束:
- `kb.search` 按 T1.5 → T1 探测降级,**出参形状不变**,消费方无感
- **双引擎按数据面分工,不做融合**:sulde(T1.5)负责 KB 沉淀检索与自动注入,
  cognee 负责会话记忆面;两面不相交,故无双重注入。跨引擎 RRF 融合仅在 hook
  日志出现"单引擎漏检"证据时再考虑
- T1.5/T2 的一切数据均可从 T0 重建;T0 不可逆向恢复(T0 是唯一要备份的东西)
- 数据格式的投入永远优先于引擎功能的投入

## 1. 分层与数据面

| 数据面 | 真源 | 增长特征 | 检索后端 |
|---|---|---|---|
| 精修知识(Layer2) | 本仓库 `knowledge/`(git) | 低频,过 SEDIMENTATION-STANDARD 人工门槛 | `kb_shared` dataset,由入图脚本从 git **单向同步** |
| 原始数据(Layer1/会话) | 各端各项目 | 高频,多端,无人工门槛 | `proj_<项目名>` / `agent_sessions` dataset,**不进 git、不进 kb_shared** |

铁律:`kb_shared` 只接受入图脚本写入(输入 = git working tree)。禁止任何端手工
`cognee-remember` 直写 `kb_shared`——质量门槛在 git PR,不在向量库。

关于 git 的定位(已定案):真源是"带 frontmatter 的 markdown 目录",git 是这个
目录的管理工具——一次打包解决多端同步(pull/push)、过审(PR)、历史回滚、备份
(每个 clone 全量)。**检索链路全程不碰 git**:查索引 → `source_path` → 读当前
文件;`source_commit` 仅是溯源标签,不是查找路径。Obsidian(本地编辑)、
Wiki.js git-sync(网页门户)、非 git 用户的表单→自动 PR 写入口,均可作为
真源之上的可选层随时加装,不动根基。

## 2. 文档 schema(标准结构化的核心)

每个知识文档入库时必须携带以下元数据:

| 字段 | 类型 | 说明 | 示例 |
|---|---|---|---|
| `doc_id` | string,稳定唯一 | 反模式用编号 `ap-NNNN`;其余用 repo 相对路径 slug | `ap-0142`、`tech-docs/案例研究/05-诊断方法论/xxx` |
| `container` | 受控词 | `anti-patterns` \| `platform-kb` \| `tech-docs` \| `case-studies` \| `work-model` | `anti-patterns` |
| `platform` | 受控词 | `android` \| `ios` \| `flutter` \| `harmonyos` \| `web` \| `cross` \| `none` | `harmonyos` |
| `title` | string | 文件名(去编号去扩展名) | 事实纠错必须重算父级聚合 |
| `summary` | string | 一句话症状/主张(取自文件首段或人工) | — |
| `source_path` | string | repo 相对路径(消费方据此回读全文) | `knowledge/anti-patterns/0142-xxx.md` |
| `source_commit` | string | 入库时的 git commit,索引可溯源 | `3249515` |
| `lang` | string | 固定 `zh` | `zh` |

sedimentation v2 文档追加三个 frontmatter 字段：`sedimentation_schema: 2`、受控
`problem_type`、`evidence_status: verified|inconclusive`。正文按语义角色切块：
`problem_context/root_cause/applicability/route_positive/route_negative/`
`outcome_positive/outcome_negative/solution/consumer`。这些角色来自
`templates/knowledge/schema.json`，不是从标题自由猜测。

**元数据载体:文件 frontmatter 优先**(T0 自描述——任何引擎、脚本、人都直接读),
目录位置仅作校验与缺省推断。新沉淀文件必须带 frontmatter(SEDIMENTATION-STANDARD
待增补此项);存量文件由脚本按目录映射一次性补齐。示例:

```yaml
---
doc_id: ap-0142
container: anti-patterns
platform: none
summary: 明细修正后父级统计必须重算而非手改缓存值
related: [ap-0109, case-studies/05-诊断方法论/动作到主力与协同肌群的可审计可视化]
---
```

`related` 是 T0 层的关系表达:没有图引擎时关系也存在(人可读、grep 可查);
有 cognee 时入图脚本将其转为**确定性图边**,不依赖 LLM 抽取碰运气——图查询质量
因此有了不受抽取模型好坏影响的下限。

切块规则:旧反模式短文 = 整文件一块;旧长文按 `##` 小节切块。v2 文档无论容器都按
语义段切块，每块附加 `section` + `role`，并继承 `problem_type/evidence_status`。
父级“判定样本”不重复索引，避免把 `route_negative` 的 `skip` 极性冲淡成普通正文。

目录 → container/platform 映射:
- `knowledge/anti-patterns/` → `anti-patterns`
- `knowledge/platform-kb/{platform}/` → `platform-kb` + 对应 platform
- `knowledge/tech-docs/案例研究/` → `case-studies`
- `knowledge/tech-docs/` 其余 → `tech-docs`
- `knowledge/work-model/` → `work-model`

## 3. 查询契约

所有消费方(本仓库 skill、其他项目、未来 MCP)只使用以下两个操作:

### `kb.search`

```
入参: {
  query:   string            # 自然语言,症状描述优先于术语
  top_k:   int = 5
  filters: {                 # 可选,受控词过滤
    container?: string
    platform?:  string
  }
}
出参: [ {
  doc_id, title, source_path, container, platform,
  role, applicability, problem_type, evidence_status,
  score:   float,
  hybrid_score: float,       # 近比分胜前的融合分
  cosine: float,             # 未归一化绝对语义相似度
  excerpt: string            # 命中块原文片段
} ]
```

`applicability` 受控为：

- `apply`：命中问题、正例、失败结果或解法，可在回读全文并核对边界后采用；
- `skip`：最高命中块是 `route_negative`，表示当前输入是显式排除样本，不得采用该规则；
- `inconclusive`：知识自身证据不足，只能继续收证据，不得自动升级为强制建议。

查询可选 `purpose=route|recall|solution|all`。自动判断“是否适用”的消费者必须用
`route`，只让显式路由正反例竞争，避免同时包含“适用/不适用”的说明段把排除输入误标为
`apply`；默认 `recall` 保留问题、根因、边界和失败表现等宽诊断入口，`solution` 聚焦正确
做法和执行正负例。v2 的辅助 `general` 小节不参与这三个目的，避免普通叙述压过显式的
`skip/fail` 样本；显式 `all` 仍可检索全部小节。旧文档因为没有语义角色，继续以
`role=general`、`evidence_status=legacy` 参与 `route/recall/solution`，保持渐进兼容。

排序先使用既有 BM25/向量融合分。只有融合分差不超过 `0.01` 的近比候选，才用未归一化
`cosine` 分胜负；`score` 复用该近比簇原有分值序列，`hybrid_score` 保留候选自身原值。
因此下游既有阈值/间隔分布不被悄悄改写，绝对相似度也不会越过明显更强的融合证据。

结构化沉淀的独立改写 canary 以“目标文档及预期语义进入 top-3”为候选召回门，并额外
要求 `skip` 排除边界位于 top-1，避免自动消费者注入相反建议。报告必须单列 exact top-1；
它是存量迁移与排序优化指标，不得靠给 v2 固定加分或放宽既有下游阈值伪造提升。

### `kb.get`

```
入参: { doc_id: string }
出参: { 全部元数据 + 全文 }    # 实现上可直接回读 source_path
```

约定:检索结果只是**线索**,agent 需要完整依据时回读 `source_path` 原文——
向量库永远不是内容真源。

### `kb.related`(可选操作,T2 在场才可用)

```
入参: { doc_id: string, depth?: int = 1 }
出参: [ { doc_id, title, relation, source_path } ]
```

关系来源:frontmatter `related` 转成的**确定性图边**(质量下限保证)+ LLM 抽取边
(增量)。T2 不可达时返回明确的 unavailable,消费方退化为直接读 frontmatter
`related` 字段。

### 实现分级(渐进增强,对应第 0 节)

`kb.search` 的每个实现(skill / hook / MCP)按 T1.5 → T1 探测降级:

1. **T1.5(主路径)**:本地混合索引可用 → BM25 + 向量加权融合 + container/platform 过滤
2. **T1(保底)**:索引不存在 → 读 `INDEX.md`(由 frontmatter 生成)交调用方 LLM
   语义匹配,辅以 grep;命中后同样回读原文

**cognee 不在 `kb.search` 主路径上**:KB 检索质量主力是 T1.5;cognee 承担
`kb.related` 图关系与会话记忆面。各级出参形状完全一致(附 `tier` 字段供调试)。

## 4. 自动注入(sulde hook):"在项目中自动找到对应沉淀"

sulde 本身是 Claude 插件,该能力由插件 hook 提供,**不依赖任何服务**。
原则:检索便宜就每轮跑,注入昂贵就设闸,一致性要求低就容忍陈旧。

**UserPromptSubmit(注入)**:每轮对当前 prompt 跑 T1.5 检索(本地毫秒级);
注入需过三道闸:
1. 融合分过阈值(阈值由 hook 日志校准:记录每轮 query 与分数,按误注/漏注调整)
2. top-1 与次名分差足够(防一批平庸命中刷屏)
3. 每轮最多 2-3 条,只注入 `doc_id`+标题+summary+`source_path`,**不注全文**

若 top-1 为 `skip` 或 `inconclusive`，本轮不得退而注入一个更弱的正候选；明确边界优先于
模糊相似度。自动注入只接受 `apply` 且非 `inconclusive` 的结果。Agent 回读全文后仍须用
路由正反例判断是否适用，并用执行正反例验收结果。

辅助规则:同一 `doc_id` 每会话只注入一次;启动时探测项目平台特征文件
(`build.gradle`→android,`Podfile`→ios,`pubspec.yaml`→flutter,
`module.json5`→harmonyos)自动加 platform 过滤/加权。

**SessionStart(索引保鲜,stale-while-revalidate)**:索引元数据记录构建时的
git HEAD;会话启动时比对,落后则后台增量重建,当下查询先用旧索引——KB 低频
变更,短暂陈旧无害。Python 环境由插件自举独立 venv(照抄 cognee 插件
`~/.cognee-plugin/venv` 模式)。

**与 cognee 并存**:按数据面分工(第 0 节)——本 hook 只注入 KB 沉淀,
cognee 自动召回只注入会话记忆,内容不相交。

## 5. cognee 后端实现映射(当前实现,可替换)

| 契约概念 | cognee 实现 |
|---|---|
| 精修知识库 | dataset `kb_shared` |
| `container` 过滤 | node_set `kb_anti_patterns` / `kb_platform_kb` / `kb_tech_docs` / `kb_case_studies` / `kb_work_model`,查询走 `node_name` 过滤 |
| `platform` 过滤 | 附加 node_set `kb_platform_{platform}` |
| `kb.related` | `POST /api/v1/recall`(graph scope);`related` 边由入图脚本确定性写入,LLM 抽取边为增量 |
| 写入 | 入图脚本 `scripts/kb-to-cognee.sh`(待实现)按 `doc_id` 幂等 upsert,manifest(路径→hash)增量 |

实现要求:
- 嵌入模型必须用中文模型(`BAAI/bge-small-zh-v1.5`,fastembed 本地)。
  **须在 A1 首次批量灌库前配置**,否则后续全量重嵌入。
- cognee 1.2.2 自带词法/混合检索(BM25 retriever、`CHUNKS_LEXICAL`、
  `HYBRID_COMPLETION`),可作 `kb.search` 的 T2 备选实现(如 MCP 服务端不想
  携带本地索引时);中文词法效果需实测。
- 入图时将受控词表(container/platform)与 `related` 语义作为本体喂
  `ontologies` 接口,约束实体抽取——降低对抽取模型质量的依赖。
- 引擎替换 = 重写本节映射 + 重建索引;第 2、3 节不变。

## 6. MCP 服务预留(v1 设计意向)

未来对外开放时,做一个**薄封装 MCP server**(FastMCP,预计 ~200 行),
部署在 A1 与 cognee 同机,HTTP/streamable 端点,多端共用:

- tools 与查询契约一一对应:`kb_search`、`kb_get`、`kb_related`(只读;不暴露 remember/datasets 等写接口)。`kb_search` 服务端实现可选 T1.5(A1 上同样本地构建索引)或 cognee HYBRID
- 鉴权:API key;只授权 `kb_shared`,Layer1 dataset 不经此服务暴露
- 不直接暴露 cognee 官方 MCP server:契约稳定性(我们的 schema 而非引擎内部结构)、
  只读收窄、引擎可替换,三个理由都要求中间隔一层自有契约
- 契约版本化:破坏性变更升 v2,MCP tool description 中声明版本

## 7. 配套轻量层(与向量检索并存)

`knowledge/INDEX.md`(待生成,脚本维护):编号 + 标题 + 一句话摘要的全量目录。
作用:人可浏览;agent 可在不依赖任何服务时直接读目录做匹配;向量层故障时的兜底。
规模超千条后仅作人用目录保留。

## 8. 待办与验证门

**KB 线(零服务依赖,可立即推进)**

1. frontmatter 补齐脚本(存量文件按目录映射生成)+ 受控词表定稿(含 `flutter`);
   SEDIMENTATION-STANDARD 增补"新文件必带 frontmatter"条款
2. INDEX.md 生成脚本(从 frontmatter 汇总,与内容同 commit)
3. T1.5 索引工具:FTS5+中文分词(jieba)+ bge-small-zh 向量,加权融合;插件自举 venv。
   **验证门:中文分词与嵌入在真实语料上的召回实测**
4. `kb-search` skill(T1.5 → T1 降级)
5. sulde hook:UserPromptSubmit 注入(三闸 + 会话去重 + 平台探测)+
   SessionStart 索引保鲜;hook 日志记录 query/分数,运行一周后校准阈值

**记忆线(cognee,与 KB 线解耦、可并行)**

6. A1 部署(cognee-selfhost/HANDOFF.md 阶段 0-2),嵌入模型按第 5 节换中文模型
7. `kb_shared` 入图脚本(`related` → 确定性图边;ontology 喂受控词表)+
   抽取质量 PoC——**PoC 结果只影响 `kb.related` 图关系增强,不阻塞 KB 检索主线**
8. MCP server(第 6 节)在多端消费需求实际出现时实施,同样带降级

**已决事项(2026-07-28,遗留项清零)**

- **真源存储**:维持 git 管理的 markdown 目录,不引入数据库/wiki/同步盘替代
  (它们要么砍过审、要么砍文件真源与离线可用)。编辑器/门户/表单写入口可作
  真源之上的可选层加装。
- **frontmatter 落位**:写进文件头(不用旁车文件)。存量批量补齐一次性完成,
  选 `knowledge/` 无在途分支的时机;迁移 commit 登记进 `.git-blame-ignore-revs`。
  既有内容行的 blame 归属不受影响(只加行不改行)。
- **`related` 维护**:沉淀时作者只写确定知道的关系,允许为空、不强制;每批
  沉淀后用 T1.5 索引跑相似度生成候选清单(零 LLM 成本),人工批准后走 PR 落盘
  ——未经人审的关系一律不落盘(与 kb_shared 铁律同源)。CI lint 校验 `related`
  目标 doc_id 存在,防悬空引用。
- **版本节奏**:知识内容 main 滚动,不设发布仪式(知识无破坏性变更语义,tag
  只会延迟送达);**版本化的是契约不是知识**——schema 破坏性变更时升 v2 并打
  tag 供旧工具 pin;可复现性靠检索结果携带的 `source_commit` 溯源。
