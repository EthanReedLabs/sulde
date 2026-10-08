# Cognee 自建共享记忆库部署方案

> 制定日期:2026-07-27
> 背景决策:数据必须自持、不上传第三方托管(已排除 Cognee Cloud);LLM 走智谱免费
> flash(API 调用可接受);server 部署在 EasePi A1(Docker + 1T 硬盘);Mac mini 与
> Windows 双机共享同一记忆库。
> 镜像已确认:`cognee/cognee:latest` 为多架构镜像(amd64 + arm64),A1 无需源码构建。
> 2026-07-30 本地验证补充:Mac 已按本文目标形态跑通 cognee 1.4.0(嵌入
> bge-small-zh-v1.5/512),写入/健康/召回链路验证结论见"已知注意点"。

## 架构

```
EasePi A1 (常开)                 Mac mini               Windows
┌─────────────────────┐
│ Docker: cognee API  │  ←──  COGNEE_BASE_URL    ←──  同左两个
│ 端口 8000           │       COGNEE_API_KEY           环境变量
│ 数据卷 → 1T 硬盘    │
│ LLM→GLM, 嵌入→本地  │
└─────────────────────┘
```

- 两台客户端的 cognee 插件检测到 `COGNEE_BASE_URL` 即自动切远程模式,共用 A1 上一份记忆
- 数据(图谱 Kuzu + 向量 LanceDB + 关系库 SQLite)全部落在 A1 的 1T 盘,不出局域网
- server 抽取知识时调用 GLM API(glm-4.5-flash,免费),嵌入在 A1 本地用 fastembed 计算

## 阶段 0 · A1 前置检查

```bash
uname -m && free -h && df -h     # 确认架构、内存、1T 盘挂载点
```

- 在路由器上给 A1 做 DHCP 静态保留(下文以 192.168.1.10 为例,按实际替换)
- 若内存 ≤4GB 且为弱 ARM 芯片,嵌入计算会偏慢(后台异步,不影响 CLI 使用);
  过于吃紧则考虑把 server 挪到 Mac mini(M4 Pro / 24GB)

## 阶段 1 · A1 部署 server

在 A1 上创建 `/mnt/<1T盘挂载点>/cognee/docker-compose.yml`:

```yaml
services:
  cognee:
    image: cognee/cognee:1.4.0   # 钉住本地验证过的版本;升级前先在 Mac 本地过一遍
    restart: unless-stopped        # A1 重启后自动拉起(关键!)
    ports:
      - "8000:8000"
    environment:
      LLM_API_KEY: "<GLM_KEY>"     # 填 Mac 上 accounts.sh 里 CLAUDE_GLM_KEY 的值;勿将本文件连 key 一起提交/外传
      LLM_PROVIDER: "custom"
      LLM_MODEL: "openai/glm-4.5-flash"
      LLM_ENDPOINT: "https://open.bigmodel.cn/api/paas/v4"
      EMBEDDING_PROVIDER: "fastembed"
      EMBEDDING_MODEL: "BAAI/bge-small-zh-v1.5"   # 中文语料主场,与 sulde KB T1.5 同款
      EMBEDDING_DIMENSIONS: "512"
      EMBEDDING_MAX_TOKENS: "512"
      LLM_RATE_LIMIT_ENABLED: "true"              # GLM 免费档并发极低,必须客户端节流
      LLM_RATE_LIMIT_REQUESTS: "8"
      LLM_RATE_LIMIT_INTERVAL: "60"
      DATA_ROOT_DIRECTORY: "/data/storage"
      SYSTEM_ROOT_DIRECTORY: "/data/system"
    volumes:
      - ./data:/data               # 全部记忆数据落此目录(即 1T 盘)
```

```bash
docker compose up -d
curl http://localhost:8000/health    # 有响应即成功;首次启动会下载嵌入模型
```

## 阶段 2 · Mac 客户端切换

1. `~/.config/cognee/env.sh` 追加(其余保留,作为断网时切回本地模式的备份):
   ```bash
   export COGNEE_BASE_URL="http://192.168.1.10:8000"
   ```
2. 清除旧 key 缓存,让插件对新 server 重新注册:
   ```bash
   rm -f ~/.cognee-plugin/api_key.json
   ```
3. 新开终端启动 `claude`,插件自动铸 key 并缓存;状态栏不再显示 `local` 即成功

## 阶段 3 · Windows 客户端

1. 退役自建网关:`notepad $PROFILE`,删除 "Cognee project memory managed block"
   那 4 行(claude/codex 两个 function 包装),重开终端确认 `claude --version` 正常
2. 安装官方插件:
   ```powershell
   claude plugin marketplace add topoteretes/cognee-integrations
   claude plugin install cognee-memory@cognee
   codex features enable hooks
   codex plugin marketplace add topoteretes/cognee-integrations --ref main
   codex plugin add cognee@cognee
   ```
3. 系统环境变量(设置 → 系统 → 环境变量,不要只写 PowerShell profile):
   `COGNEE_BASE_URL = http://192.168.1.10:8000`
4. 把 Mac 的 `~/.cognee-plugin/api_key.json` 复制到 Windows 的
   `%USERPROFILE%\.cognee-plugin\api_key.json`,两机共用同一身份

## 阶段 4 · 验证与运维

- 联通验证:Mac 上"记住:测试共享记忆" → `/cognee-memory:cognee-sync` →
  Windows 新会话问"共享记忆测试是什么"能召回即打通
- 备份:A1 上 `tar czf cognee-backup-$(date +%F).tgz data/`(建议每周/cron)
- 升级:`docker compose pull && docker compose up -d`
- 安全红线:8000 端口只留局域网,不做公网端口映射;compose 文件含 key,注意权限

## 阶段 5 · Ontology 引导抽取(A1 数据首灌前完成,2026-08-05 排入)

**价值**:用 KB 受控词表锚定实体抽取——垃圾实体减少、输出 token 更小、图更净、检索噪音更低。
这是配置层优化吃尽后的下一个数量级降本/提质点。

**接入成本已确认极低**(1.4.1 实测源码):ontology 走 `.env` 配置而非库级改造——
`ONTOLOGY_RESOLVER=rdflib`(默认)、`MATCHING_STRATEGY=fuzzy`(默认)、
`ONTOLOGY_FILE_PATH=<OWL文件路径>`(唯一需要提供的)。管道里 OntologyAdapter 常驻,
未喂文件时日志刷 "No close match found"——喂上即生效。

**本体来源**:KB frontmatter 词表自动生成,零人工维护:
- 类(classes):容器 5 类(anti-patterns/platform-kb/tech-docs/case-studies/work-model)、
  平台 7 词(android/ios/flutter/harmonyos/web/cross/none)、实体类型(反模式/案例/技能/模板)
- 个体(individuals):doc_id 全集(ap-NNNN + 路径 slug)
- 关系谓词:belongs_to_container / applies_to_platform / related_to(源自 frontmatter `related`)

**实施步骤**:
1. `scripts/kb/build-ontology.py`:从 git 真源生成 OWL(RDF/XML),纳入 CI 与 INDEX 同保鲜
2. Mac 本地 PoC:20 篇小 dataset 带/不带 ontology 对比——实体总数、垃圾实体占比、
   每篇 token 消耗(usage_logging 已开,可直接查)、golden 式召回质量
3. 过关标准:垃圾实体 -30% 以上且召回质量不降 → A1 首灌即带 ontology 上线
4. 不过关:留存对比证据,回退默认抽取,本体文件仍可作 `related` 关系校验用

**排序**:A1 阶段 1(server 部署)之后、数据首灌之前;Mac PoC 可提前独立做(不依赖 A1)。

## 已知注意点(含 2026-07-30 本地验证结论)

- **数据迁移(替代旧"从零开始"方案)**:同版本 + 同嵌入配置(bge-small-zh-v1.5/512)
  前提下,停 server 后把 Mac `~/.cognee` 整目录拷入 A1 数据卷即可直接沿用;嵌入配置
  不一致时向量不可复用,只能重放(把关键事实重新 remember)。Mac 侧已有全量备份
  `~/cognee-backup-2026-07-30-pre-bge.tgz` 保底
- **1.4.0 remember API 是破坏性变更**:multipart Form 而非 JSON;`data` 必须是文件
  part(`-F "data=@file"`),`datasetName` 为 Form 字段;且必须 `run_in_background=true`,
  同步模式会占死 uvicorn 单 worker 使 /health 无响应
- **remember 不触发图谱构建**(1.4.0):它只入 data 表 + memify,图谱必须显式
  `POST /api/v1/cognify` `{"datasets":[...],"run_in_background":true}`(或由插件
  sync 脚本代劳);进度查 `GET /api/v1/datasets/status`——"图谱永远为空"多半是这个
- **LLM 供给终选:阿里百炼 qwen3.7-flash**(OpenAI 兼容端点,2026-07-31 实测:单文档
  cognify 1 分钟完成、零 429、召回精准)。GLM 免费档配额撑不住 cognify 并发;本地
  Ollama qwen3:14b 质量可但 22 tok/s 吞吐撑不住 improve 循环+cognify 并发(排队超时)。
  节流配置 60 次/分钟——过紧(如 8/分钟)会让 improve/cognify/召回同队列互相饿死
- **嵌入终终选:本地 fastembed bge-small-zh-v1.5/512(2026-08-05 定稿)**——零 API 成本、
  离线可用、key 轮换不动记忆数据。百炼 1024 曾于 08-03~08-05 短暂服役,数据归档
  `~/cognee-1024-archive-2026-08-05/`;换回动机:key 轮换事故暴露"嵌入依赖在线 key =
  记忆可用性绑在计费系统上"。**LLM 终选 qwen3.6-flash @ token-plan 业务空间端点**
  (2026-08-05 key 轮换后,注意:百炼 key 按业务空间隔离,key 必须配对其空间专属端点,
  跨空间报 invalid_api_key)。历史适配记录(百炼嵌入如再启用):
  ①litellm 对自定义端点不认 dimensions 参数→需 `LITELLM_DROP_PARAMS=true`(注意:必须
  进**进程环境**,pydantic 读 .env 不会导出给 litellm——launchd setenv + 手动启动显式
  export 双保险);②百炼嵌入批大小上限 20→`EMBEDDING_BATCH_SIZE=10`;③本地备份 bge/512
  配置保留在 .env 注释区,离线场景可切回(需按下述清库重灌)
- **`Spill has sent an error` 的真身(2026-08-03 定案,曾误判为 server 语境缺陷)**:
  lance merge_insert 遇到**向量维度与既有表不一致**时抛出的就是这个不可读错误(两行
  裸 lancedb 即可复现:512 维表 merge 1024 维行)。当时"server 必现/进程外全过"的
  假象来自下一条"双存储宇宙"——server 一直在撞旧维度表,隔离复现全是新目录。上游
  已附最小复现(topoteretes/cognee#4313)。**换嵌入模型必须:停 server → 清
  dataset_database/datasets/dataset_data/acls/pipeline_runs/data/nodes/edges + 归档全部
  向量/图谱文件(两边一起,防"状态已处理、库中无物"脑裂)→ 重启重灌**
- **双存储宇宙陷阱(必配!)**:cognee 默认 system/data 根解析在**包安装目录内**
  (`site-packages/cognee/.cognee_system`),不是 CWD 也不是 `~/.cognee`——手动启动、
  venv 迁移后极易出现"清库清了 A 宇宙、server 写着 B 宇宙"的错位(本机实战:B 宇宙
  静默服役 3 天,清库/重灌全打在休眠的 A 宇宙上)。**根治:`SYSTEM_ROOT_DIRECTORY`/
  `DATA_ROOT_DIRECTORY` 显式写进 `~/.cognee/.env` 钉死**;部署新机后用
  "改 .env 前后 cognee_db mtime 是否变化"验证唯一宇宙
- **server 重启后旧 api_key 失效**(1.4.0 多租户,key 随 default user 身份重建):插件会
  自动重新铸 key;手工调用需重登 `/api/v1/auth/login` → `GET/POST /api/v1/auth/api-keys`
  换新 key。跨机复制 api_key.json 后若 server 重启过,需重新同步
- **GLM 免费档配额是 cognify 的硬瓶颈**:cognee 实体抽取并发调 LLM,免费档瞬间打爆并
  触发账户级限额(整日 429);上表节流参数只能防"自己打爆自己",配额耗尽只能等窗口
  重置。若 cognify 长期跑不完,评估 GLM 付费档或换供应商(只改 LLM_* 三个变量)
- **嵌入是本地 fastembed、不走 GLM**:限流只影响图谱抽取,不影响会话缓存写入与向量
  召回——因此免费档下"缓存记忆可用、图谱增强延迟到位"是可接受的降级形态
- **token 消耗暗点(2026-08-04 源码勘探 WP15,文档没写的)**:①每个进程启动做 1 次
  LLM+1 次嵌入连接探测(还可能 30s 超时卡启动)→ `COGNEE_SKIP_CONNECTION_TEST=true`
  关掉;②查询不显式传 searchType 时 query_router 可能路由到 GRAPH_SUMMARY_COMPLETION
  (每查 2 次 LLM)——自有脚本/MCP 一律显式传类型;③重试放大器:结构化输出失败
  instructor 最多 2 次修复 × tenacity 外层重试,最坏一个逻辑调用放大到 ~18 次请求;
  ④嵌入超长输入按 2/3 重叠二分递归,重叠部分重复计费——入库前控制单块长度;
  ⑤improve 传 session_ids 会触发乘法链(trace/QA cognify+curator+每 lesson writer+
  再 cognify),长会话尤其贵;⑥抽取 prompt 可换内置精简版 `GRAPH_PROMPT_PATH=
  generate_graph_prompt_simple.txt`(-54% 输入,免逐边描述省输出);⑦分层模型路由
  `LLM_EXTRACTION_MODEL`/`LLM_SUMMARIZATION_MODEL`/`LLM_QUERY_MODEL` 可按任务难度
  配不同价位模型(A1 可用)
- `DATA_ROOT_DIRECTORY`/`SYSTEM_ROOT_DIRECTORY` 变量名及 `/health` 路径如遇镜像
  版本差异报错,记录实际输出后调整
- Windows 旧自建系统 `D:\AIProjects\cognee-project-memory` 确认新方案稳定后可整体归档删除
