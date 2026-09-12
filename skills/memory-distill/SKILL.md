---
name: memory-distill
description: 会话内记忆蒸馏——当前 Claude Code 或 Codex 宿主读取近期记忆原文,抽取实体关系入图谱,提炼教训并路由沉淀候选。周期性或按需触发。
---

# /memory-distill:记忆蒸馏(当前宿主即记忆系统的 LLM)

## 定位

sulde-mem 的存取是零 LLM 的;**智能加工在这里发生**——由当前 Claude Code 或 Codex
会话执行,产出走 CLI 确定性落库,每条可审计。不得因为另一宿主也已安装而切换提供方。

## 流程(五步,全程本仓库 CLI)

### 1. 拉取待蒸馏窗口

```bash
SULDE_KB_HOME="${SULDE_KB_HOME:-${SULDE_HOME:-$HOME/.sulde}/data/kb}"
SULDE_KB_INDEX="${SULDE_HOME:-$HOME/.sulde}/bin/kb-index"
STATE="$SULDE_KB_HOME/distill-state.json"   # {last_id: N},不存在则从头
"$SULDE_KB_INDEX" mem-recent -n 100  # 或按 last_id 过滤
```

窗口原则:一次蒸馏 ≤100 条;超出分批,先近后远。

### 2. 阅读原文,产出结构化抽取(你的智能在这一步)

对窗口内容做三类提炼,输出**一个 JSON**:

```json
{
  "entities": [{"name": "双存储宇宙", "type": "incident"}],
  "edges": [
    {"src": "Spill错误", "rel": "root_caused_by", "dst": "维度不匹配merge", "entry_id": 2851, "confidence": 0.95}
  ],
  "lessons": [
    {
      "text": "换嵌入模型必须把所有派生存储一起重建,防脑裂",
      "problem_type": "workflow",
      "task_context": "替换嵌入模型并迁移已有索引",
      "symptom": "检索结果仍混用旧维度,期望全链一致但实际部分存储未更新",
      "root_cause": "关系与向量派生存储没有共享同一迁移闭环",
      "evidence_status": "verified",
      "evidence_entry_ids": [2851],
      "route_positive": {"text": "更换嵌入模型后部分检索仍返回旧结果", "reason": "命中模型迁移与派生状态残留", "source": "observed"},
      "route_negative": {"text": "只调整查询权重且嵌入维度未改变", "reason": "没有发生模型或向量结构迁移", "source": "constructed"},
      "outcome_positive": {"text": "所有派生存储重建并通过一致性抽检", "reason": "覆盖全部派生状态并留下验证证据", "source": "constructed"},
      "outcome_negative": {"text": "只清空向量表就宣称迁移完成", "reason": "其他缓存和图状态仍可能引用旧模型", "source": "observed"}
    }
  ]
}
```

抽取纪律:
- 实体用**中文短名词**,同一事物全窗口统一叫法(共指消解是你的职责)
- 边必须能从原文支撑,`entry_id` 标出处;推断的边 confidence ≤0.7
- **宁缺毋滥**:一次蒸馏 5-15 条边是健康量,不要为凑数建边
- lessons 只收"下次会再用到"的;一次 ≤5 条。每条使用 Layer1 问题卡结构，必须含
  问题语境、症状/差异、证据状态和四类样本；样本来源区分 `observed|constructed`

### 3. 图谱落库

将抽取结果拆成图谱载荷与 lessons；`mem-annotate` 只接收 entities、edges 和
显式 extracted_by（当前 Codex 为 codex、Claude Code 为 claude）。每批最多 6 个
实体、3 条边，边的两个端点都须在该批实体中声明；不要把 lessons 整体传给写入器。

```bash
"$SULDE_KB_INDEX" mem-annotate --json '<仅图谱字段和当前宿主 extracted_by 的 JSON>'
```

### 4. lessons 路由(人工门禁不可绕)

逐条判断:
- 跨项目通用、够格进 KB → 走 `/sediment` 流程(判重/脱敏/成文全套)
- 项目私有或还不成熟 → 保留在蒸馏记录里,下次复审

### 5. 更新状态 + 记录

```bash
echo '{"last_id": <本次最大id>, "ts": "<ISO时间>"}' > $STATE
```

向用户汇报:窗口条数、入图边数、沉淀候选数与去向。

以 created / already_present 回执及独立回读为准；conflict 不覆盖旧来源，unknown
不重新执行写入。保留请求摘要和问题供 reconcile-verifications 独立验证。
蒸馏本身是本任务目标时，未完成的登记不能报成功；普通业务任务中的可选里程碑增强
失败，则先在已授权的任务报告保留候选，不阻断不依赖该结果的业务工作。

## 触发时机

- 周校准报告(每周日 LaunchAgent)提示后,任意会话说"做记忆蒸馏"
- 大战役收尾时(如本次 cognee 迁移)主动做一次
- 两种宿主均可使用全局规则中的 CLI；已接 MCP 时也可用 `memory_annotate`

## 铁律

- 抽取产物只进 memory.db(本地私有);进 KB 的唯一通道是 /sediment
- 不修改 mem_entries 原文——原文即真相,蒸馏只做增量标注
