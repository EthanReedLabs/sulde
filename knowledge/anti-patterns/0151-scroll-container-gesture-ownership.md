---
doc_id: "ap-0151"
container: anti-patterns
platform: harmonyos
summary: "滚动容器内多手势共存:先划事件所有权矩阵,再写手势代码"
related: [platform-kb/harmony/arkui-layout-scroll-shell]
sedimentation_schema: 2
problem_type: bug-fix
evidence_status: verified
---

# 0151 — 滚动容器内多手势共存:先划事件所有权矩阵,再写手势代码

- **平台**:HarmonyOS
- **复发次数**:2
- **lint 状态**:❌ 无法静态检查(手势竞争是运行时行为)→ 进 task 起草 / 真机验收 checklist

## 问题原型

一个滚动容器(`Scroll` / `List` / `Grid`)内需要同时支持多种交互:原生上下滚动 + 弹性惯性、长按拖拽排序、item 主点击、item 右上角更多 / 删除 / checkbox 等子控件。多轮修改中反复出现互斥:

- item 区域上下滑动不跟手,只能在 item 之间缝隙滑动。
- 长按拖拽能用后,右上角更多按钮无法触发。
- 滚动能用后,拖拽动画或拖拽事件又退化。
- 手写 fling 能模拟惯性,但达不到原生 `Scroll` 的极致流畅。

症状的共同特征:每加一种交互就打断另一种,靠反复调阈值 / duration 掩盖,上限始终低于原生。

## 为什么错

### 1. 没有先划分事件所有权

把「滚动、长按、拖拽、更多点击」全挂到同一层 item / overlay 上,让多个 gesture 默认竞争。错误模型:

```
item outer Stack = HitTestMode.Block + LongPressGesture + PanGesture + onClick
```

这个模型让 item 外层成为手势拦截区:纵向滑动先进 item 手势链,原生 `Scroll` 拿不到完整触摸序列;子控件是子节点,但父层 LongPress/Pan 仍参与竞争;为拖拽加的拦截会破坏点击,为点击放开的命中又会破坏拖拽。

### 2. 把系统滚动物理误当作可手写替代

为解决拖拽时 scroll 抖动,改用透明层接管所有 touch,再用 `Scroller.scrollTo` + `setTimeout(16ms)` 手写滚动和 fling。这样能避免拖拽事件泄漏,但失去系统级 velocity tracker、帧同步、fling 曲线和 edge effect:快速上滑抬起不能一次滚到底,逐帧 fling 不够顺滑,参数越调越多而上限始终低于原生 `Scroll`。

### 3. 未区分「观察态 overlay」和「接管态 overlay」

正确做法不是「始终透明」或「始终 Block」,而是按状态切换。缺状态机时,overlay 常驻 `HitTestMode.Block` 会长期阻断下层滚动和子控件。

### 4. 透明父层不代表后代命中树已经放行

在一个全屏滚动页上，为悬浮导航扩大透明承载区后，仅缩小父级 responseRegion，
实体外拖动仍不能使下层 List 滚动。按实际触点排除实体外导航子树后，列表位移恢复，
实体导航点击仍保留。这证明父级透明外观或响应区设置不足以证明整棵后代树已放行。
该结论限定于已测载体；不同组件和版本须验证自己的命中语义，不能把某一个 HitTestMode
枚举当成所有 overlay 的万能处方。

## 适用边界

- 适用于滚动与点击/拖拽等多种手势竞争，以及透明 overlay 后代抢走页面触摸。
- 列表已经没有更多数据、内容未超过视口、或纯布局遮挡而没有触摸竞争时，不直接套用事件所有权修复。
- 需要比较同一实际触点的命中链和滚动前后 offset；静态透明截图或属性存在不构成放行证据。
- 本条保留原拖拽场景经验；新增透明导航变体不表示原所有场景已在新设备重测。

## 判定样本

### 路由正例

- **输入**：item 主体滑不动而缝隙可以滑，加入长按拖拽后子按钮又点不到。
- **预期**：apply
- **原因**：多个交互在同一层竞争，原生滚动与子控件缺少明确 owner。
- **来源**：observed

- **输入**：透明导航承载层缩小 responseRegion 后，实体外拖动仍被后代拦截，下面的列表不滚动。
- **预期**：apply
- **原因**：需要核对整个命中子树，而不是只看父层透明度和响应区。
- **来源**：observed

### 路由反例

- **输入**：没有覆盖层也没有新增手势；列表只有一条数据，内容短于屏幕，因此无法继续滚动。
- **预期**：skip
- **原因**：没有可滚动空间，不是事件竞争；不能通过接管触摸制造滚动。
- **来源**：constructed

### 执行合格例

- **做法或输出**：实体外排除导航子树后，下层 List 的真实 offset 随拖动变化，实体按钮仍正常切换。
- **预期**：pass
- **原因**：同时验证需要放行和需要保留的两类交互。
- **来源**：observed

- **做法或输出**：原生列表拥有滚动，进入 dragging 后覆盖层才接管，退出后恢复，更多按钮仍独立可点。
- **预期**：pass
- **原因**：事件所有权随状态转换，未以手写 fling 代替原生滚动物理。
- **来源**：constructed

### 执行失败例

- **做法或输出**：父级 responseRegion 已缩小，但实体外真实拖动时 List 的位置仍未变化。
- **预期**：fail
- **原因**：属性设置不等于后代命中链已放行。
- **来源**：observed

- **做法或输出**：透明层常驻 Block，再用定时器手写 scroll/fling，只有拖拽顺畅而正常滚动退化。
- **预期**：fail
- **原因**：用另一套滚动物理掩盖竞争，破坏原生完整触摸序列。
- **来源**：observed

## ✅ 正确

滚动容器内存在 2 种以上交互时,**先写事件所有权矩阵和状态机,再写 ArkUI 手势代码**。

### 事件所有权矩阵(实施前必写)

| 交互 | Owner | 禁忌 |
|---|---|---|
| 正常上下滑动 / fling / bounce | 原生 `Scroll/List/Grid` | 透明层手写 scroll/fling 作默认方案 |
| item 主点击 | item 内部可点击区 | 父层全域 `HitTestMode.Block` 抢点击 |
| item 子按钮 / more / delete | 子按钮自身 | 父层 LongPress/Pan 与子按钮竞争 |
| 长按候选 | overlay / 轻量 watcher | 候选态处理滚动 |
| 拖拽移动 | 拖拽态 overlay / drag layer | 未进入拖拽就拦截 Scroll |
| 排序提交 | state / repository | 拖动视觉变化后不提交真实顺序 |

### 状态机(显式实现,不靠 gesture 默认竞争)

| 状态 | hitTest / 手势策略 |
|---|---|
| idle | 原生 Scroll 滚动;overlay `Transparent` 或无拦截 |
| candidate | 记录 down 点和 item;移动超阈值则取消候选,交回 Scroll |
| dragging | overlay `Block`;锁 scroll offset;只处理拖拽 |
| settling | 播放 settle/reorder 动画;提交排序 |
| restored | overlay 回 `Transparent`;Scroll 恢复原生 |

### 关键原则

1. **原生 Scroll 优先**:用户在滑动时,让原生 Scroll 拥有完整触摸序列,保 velocity/fling/edge effect(如 `EdgeEffect.Spring`)。
2. **拖拽态才接管**:长按成立前 overlay 不接管滚动;成立后才切 `Block` 并锁 offset。
3. **子控件独占子事件**:more/delete/add/handle 等子控件单独 `HitTestMode.Block` + `onClick`,不被父层 Pan/LongPress 覆盖;item 主体若不该阻断滚动则 hitTest `None/Transparent`。
4. **视觉和提交分离**:拖动中用 visual order,松手后再提交真实 state。
5. **用状态切换解决冲突,不靠阈值堆叠**:子按钮点不动 / item 滑不动时,先查父层是否抢事件、命中链是否被拦,而非继续调 threshold / physics。

### 诊断顺序(复用)

冲突多是 owner 不清所致:item 外层抢 Scroll → 上滑不动;item 外层抢子控件 → 更多菜单不出;透明层全接管能保拖拽但牺牲原生滚动物理。修复不是继续调阈值,而是改 owner —— Scroll 拥有滚动、子控件拥有点击、overlay 只在 dragging 态拥有拖拽。

悬浮导航变体还需分别列出实体、透明留白、后代和下层页面的 owner；检查响应区坐标转换、
触点起始位置与整段手势的归属。Transparent/None 等名称本身不能替代平台实际命中验证。
几何上内容仍被底栏覆盖时，另查页面避让预算，不以不断增加空白掩盖触摸问题。

## 消费与防复发

- ❌ 无法静态检查(手势竞争是运行时行为)。落地为 task 起草 / 真机验收强制段:
  1. **事件所有权表**:scroll owner / item click owner / sub-action owner / drag owner。
  2. **手势反搜**:`.gesture(`、`.parallelGesture(`、`.onTouch(`、`.hitTestBehavior(`、`.edgeEffect(` 逐个核 owner。
  3. **状态机表**:idle / candidate / dragging / settling / restored。
  4. **禁止项自检**:item 全域 `Block`?overlay 常驻 `Block`?手写 scroll/fling 替代原生?
  5. **真机验证**:item 主体滑动能完整 fling、缝隙滑动一致、子控件可点击、新增项点击不触发拖拽、长按可拖且拖拽时 Scroll 不抖、拖后提交顺序、light/dark 拖拽反馈一致。
