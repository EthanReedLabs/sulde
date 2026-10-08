# KB 检索实施方案(执行基线)

> 依据:`kb-retrieval-contract.md`(收敛稿)。分支:`feat/kb-retrieval`。
> 两条线:KB 线(WP1-5,零服务依赖)+ 记忆线(A1/cognee,并行、不阻塞)。

## KB 线工作包

### WP1 frontmatter 补齐 + 词表定稿(~0.5 天)

- `scripts/kb/add-frontmatter.py`:遍历 `knowledge/`,按目录映射推导
  `container`/`platform`;`doc_id`:反模式取文件名编号(`ap-NNNN`),其余路径 slug;
  `summary` 首段启发式提取后**人工过一遍**;幂等(已有 frontmatter 跳过)
- `scripts/kb/lint-frontmatter.py`:受控词合法、`doc_id` 全局唯一、`related`
  无悬空(即 CI 检查项)
- SEDIMENTATION-STANDARD 增补"新文件必带 frontmatter"条款;迁移 commit 登记
  `.git-blame-ignore-revs`
- 验收:lint 全绿;批量改动单独一个 commit

### WP2 INDEX.md 生成(~0.25 天,依赖 WP1)

- `scripts/kb/build-index-md.py`:从 frontmatter 汇总,按 container 分组一行一条
- 接入仓库 verify/tests 校验 INDEX 与 frontmatter 一致

### WP3 T1.5 索引工具(~1-1.5 天,核心,依赖 WP1)

- `tools/kb-index/`(Python 包)+ venv 自举脚本
- BM25 侧:sqlite FTS5 + jieba 预分词;向量侧:fastembed `bge-small-zh-v1.5`,
  **numpy 暴力余弦**(向量存 sqlite BLOB;千级块规模不引 sqlite-vec,砍掉
  Windows 原生依赖风险,过万条再换)
- 融合:归一化加权 0.5/0.5 起步,权重进配置
- 索引 `.kb-index/kb.db`(gitignore):manifest 表(路径→hash 增量)+
  meta 表(git HEAD / 模型名 / schema 版本)
- CLI:`kb-index build`;`kb-index search "..." --container --platform -k --json`
  (输出契约 JSON,带 `tier`)
- 首次构建下载模型 ~100MB,国内配 `HF_ENDPOINT` 镜像
- **验收 = 验证门**:golden set 20 条"换个问法"查询(只述症状不含原文关键词),
  hit@5 ≥ 80%。不过关:调分词/权重 → 换 `bge-base-zh`

### WP4 kb-search skill(~0.25 天,依赖 WP3)

- `skills/kb-search/SKILL.md`:封装 CLI;降级逻辑(db 缺失 → 读 INDEX.md 由
  agent 匹配);强制"命中后回读 `source_path` 原文"

### WP5 两个 hook(~0.5-1 天,依赖 WP3)

- UserPromptSubmit:T1.5 检索 → 三闸(阈值 / top-1 分差 / ≤3 条只注元数据)→
  注入;会话级 doc_id 去重;平台探测按项目缓存;query+分数写 jsonl 日志
  (一周后校准阈值);短 prompt / 斜杠命令跳过
- SessionStart:venv 自举;db meta HEAD 落后当前 HEAD → 后台增量重建
- 验收:真实项目跑一天,日志有流水、注入合闸、无刷屏

### 里程碑

| 里程碑 | 标志 |
|---|---|
| M1 | WP1+WP2 合入,T0/T1 成立 |
| M2 | WP3 golden set 过关,T1.5 成立 |
| M3 | WP4+WP5 上线,"自动找到"Mac 跑通 |
| M4 | Windows 端验证(venv 自举 + hook 兼容为主要风险) |

## 记忆线(并行)

1. A1 部署(`cognee-selfhost/HANDOFF.md` 阶段 0-2),嵌入模型换 `bge-small-zh-v1.5`
   ——等 A1 机器信息/SSH
2. `kb_shared` 入图脚本(`related`→确定性图边;ontology 喂受控词)+ 抽取 PoC
   (只影响 `kb.related`,不阻塞主线)
3. Windows 接入(HANDOFF 阶段 3-4);MCP server 按需启动

## 执行方式

- 每 WP 委托 codex 执行(跨文件 / >10 行),Claude 负责任务书、验收、golden set 评测
- WP1→WP2 串行;WP3 后 WP4/WP5 可并行;每 WP 独立 commit
