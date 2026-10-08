# Full-Harness public export: local review result

Date: 2026-09-12. Status: **review candidate only; publication not accepted**.

This is the initial baseline report. See [R1-report.md](R1-report.md) for the
subsequent fixes and passing bounded probes; the original failure evidence below
is preserved rather than overwritten.

## Confirmed boundary

The user permits publishing functionality, but not the formal Sulde knowledge
corpus or project/session memory. This also excludes their index/vector
payloads, inventories, history and backups. Production ledgers, installation
receipts, internal task reports, credentials and private Git history remain
private. Engine code and schemas are not operational data.

This task did not change either formal data store, the production installation,
private main/dev, the public checkout or any remote. The existing three `.ua`
edits in the private main checkout remain untouched.

## Implemented locally

- Separate, review-only exporter; the legacy Community exporter is unchanged.
- Frozen Git-blob inputs, explicit per-file modes/hashes/provenance, output
  inventory readback, path/symlink checks, and no existing-directory overwrite.
- Empty generated corpus metadata; public LICENSE and standalone CLI retained.
- Private findings/report outside the candidate's export tree, ignored by Git.
- Bounded probe driver with a new synthetic Git checkout and isolated data root.
  It runs no installer, scheduler registration, production mutation or push.

Input commits:

- Private source: `e61683c08aaf97db3e8e9d105ea3154ec217061c`.
- Existing public baseline: `c966bae1477423ee3a64fd2a6d02fdcb91a43913`.

Candidate: `.sulde/public-export/review-002/tree`.
Private per-file manifest: `.sulde/public-export/review-002/review.json`.
Manifest digest: `1a9339edf16f4e086e46bcc6a646bd2aba25017be691ce9bf724cc8575a78743`.

The candidate has 592 files: 551 private-repository implementation files,
37 retained public files and four generated boundary/empty-data files. All
399 files under the source formal `knowledge/` tree are excluded, including
the source index and manifest. Only a newly generated empty manifest and index
exist under the candidate `knowledge/` tree. No private Git objects are copied.

## Actual verification

Evidence: `.sulde/public-export/validation-001/results.json` and per-probe logs.

| Check | Actual result |
|---|---|
| New exporter boundary regressions | 12 passed |
| Empty KB build | Passed; manifest/chunks/vectors tables each have zero rows |
| Empty memory initialization | Passed |
| Real MCP stdio initialization and tools/list | Passed |
| Real MCP empty KB query | Passed; returned `[]` |
| Real MCP empty memory query | **Failed**; attempted model initialization despite zero memory entries |
| Corpus manifest regressions | 5 passed |
| KB index common regressions | 8 passed |
| MCP entry regressions | 9 passed |
| Knowledge history regressions | 5 passed |
| Existing public toolkit regressions | 7 passed, **3 failed** |
| Claude artifact staging | Passed with empty corpus |
| Codex POSIX/Windows artifact staging | Both passed with empty corpus |
| Official Codex plugin structure validator | Both generated Codex packages passed |

Packaging Windows files is **not** Windows execution. Source tests are **not**
live-host or production installation evidence. Full source tests, bootstrap
installation and real Hook canaries have not been run for this candidate.

## Release blockers and next implementation work

1. **Empty memory query unnecessarily loads a model.**
   `tools/kb-index/memory.py:445` calls `_model()` before checking whether any
   memory rows/vectors can contribute. The synthetic no-data/no-model-cache
   MCP probe took 39.656 seconds and returned an error. This is not a reason
   to distribute private memory or model caches. Add a tested empty-store
   fast path; retain nonempty-store embedding/search semantics.
2. **Community and full-Harness integration must be reconciled.**
   Public `VERSION` still describes the old release, while the imported Claude
   manifest is version 0.8.4. The old CLI doctor/tests require `run-hook.sh`,
   while the imported Hook manifest invokes Python entrypoints directly. Three
   public-toolkit tests fail. Reconcile version identity and the real launcher
   contract; do not weaken assertions just to report green.
3. **Public portability/privacy adaptation remains.**
   The review scanner reports 95 findings, not 95 confirmed leaks. They include
   real machine-specific paths and business-specific examples, but also
   synthetic negative-test credentials and the already-public scanner's own
   redaction markers. Review by exact file/content; preserve safety-test intent.
   In particular the audited Codex executable is a private-machine absolute
   path. Its public configuration must retain executable/version verification,
   not silently replace it with an unchecked PATH lookup.
4. **Data-dependent documentation and fixtures need replacement.**
   Supply a data-free normative sedimentation guide and genuinely synthetic
   regression fixtures. Do not copy production-derived ledgers or formal corpus
   documents to make tests pass. Update the public README/capability description
   and private-corpus-dependent tests before full-source verification.
5. After those changes, freeze a new candidate, run full candidate tests and
   real isolated host checks, then approve the exact public target/snapshot.
   Publication must preserve the public repository's own history and license.

No task commit, merge, installation or push has been performed. The task branch
and local evidence are retained for continuation; the candidate is not ready to
publish. No core runtime fix is claimed in this report.

## 沉淀候选 — 空数据发布不能以携带生产数据消除启动依赖

### 任务与意图

- 问题类型：performance / workflow。
- 任务目标：公开完整 Harness 能力但保留正式知识和项目记忆。
- 用户真实预期：公开能力代码，不同步上述数据。
- 触发场景：空语料、空记忆、无模型缓存的隔离发布候选。

### 观测与证据

- 可观察症状：KB 查询返回空数组；空记忆查询加载模型，重试后失败。
- 期望与实际差异：没有可检索数据时应能正常返回空结果，不应为得到空结果下载模型。
- 已确认根因：记忆查询在检查候选数据前无条件调用 `_model()`。
- 已排除假设：KB 索引未建、记忆 schema 未初始化、MCP 未启动均被独立探针排除。
- 证据状态：verified（失败事实及调用顺序）；修复有效性尚未验证。
- 一手证据：上述源码与 `validation-001/mcp-stdio-empty-queries.log`，摘要
  `a9d1e3f0dde81b662b1077e58367794f3d26b4664f140c1bedefd9daee85e95a`。
- 正确做法及验证：待实施空存储路径，补无模型加载断言与非空回归，再重跑真实 stdio。

### 正负样本素材

| 样本 | 内容 | 预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 空记忆库查询仍初始化或下载模型 | apply | 无数据却承担推理依赖 | observed |
| 路由反例 | 非空向量检索需要已配置模型 | skip | 真实候选需要语义评分 | constructed |
| 执行合格例 | 空库返回空数组，模型工厂未调用，非空排序保持 | pass | 数据边界与原有语义同时保持 | constructed |
| 执行失败例 | 打包成功即宣称可用，实际空查询仍失败 | fail | 工件结构不等于能力可用 | observed |

### 上浮边界

- 必须泛化：项目、路径、提交、任务身份与原始日志。
- 可复用内核：公开能力与私有数据分离必须验证空数据真实调用链。
- 建议容器：work-model。
- 候选消费者：发布检查清单、空数据回归、MCP 验收。
- 本阶段仅保存在私有任务汇报；没有额外写入正式知识或记忆存储。
