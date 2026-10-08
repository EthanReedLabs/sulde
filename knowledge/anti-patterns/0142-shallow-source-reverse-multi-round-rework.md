---
doc_id: "ap-0142"
container: anti-patterns
platform: cross
summary: "浅层反抽源码(grep 采样 + 无运行时实证 + 无跨端能力探针)→ 累积漂移 + 多轮返工"
---

# 0142 — 浅层反抽源码(grep 采样 + 无运行时实证 + 无跨端能力探针)→ 累积漂移 + 多轮返工

- **平台**:跨端
- **复发次数**:5
- **lint 状态**:⏳ pending(待 task md / handoff baseline hook 加「反抽完整性 + UI 一轮交付」gate)

## 现象

已有一份成熟的源实现(旧平台已上线),向新平台做 1:1 转译还原,理论上应 **1-2 轮收敛**,实际 **每个模块 3+ 轮才跑通**。

每轮 Dev shipped 后,真机走 flow 又发现新 drift → 协调端回头深抽 → 派 fix → 再发现新 drift → …「补丁式」迭代。

**症状特征**:

- 协调端反抽出的真值文档看着「很完整」(节点树 + endpoint 表 + 视觉描述齐),Dev shipped 后真机一跑就 drift。
- 每轮 fix 修 N 个 drift,同时暴露 M 个新 drift(累积式,不收敛)。
- 漂移先出在「看得见的主页面结构」,后续才逐层暴露:选中态 / 禁用态 / 空态 / 最后一步 / 报告页 / 弹窗分支 / dark-light 色值 / 图标 tint / 资源差异 / 状态栏与底部安全区。
- 已有的新平台代码被当成「可小修的基线」,实际它只是早期不完整实现,继续补丁把结构差异藏进后续交互态。
- 同类 drift 跨模块反复复发(团队记忆衰减)。
- 用户反复 ping「这功能跑不通」「跟旧平台不一样」,靠肉眼逐项指出 drift。

## 为什么

多轮返工的根因不是「某一处抄错」,而是 **反抽方法本身浅**——静态 grep 采样代替了完整深读,且缺三类实证。可归为几个 process gap 的叠加:

1. **静态 grep 浅采 ≠ 全文件深 Read**
   只 grep 命中关键字就下结论,没读调用方函数体、没读传入参数。典型:某组件某个元素被调用方 hardcode 关掉永不渲染,只看组件定义会误判它存在。

2. **缺调用图 / call graph**
   入口 handler、Action handler、条件分支未全表拉出。同一组件在不同入口传不同参数(如品牌分支、type 映射错位),不追调用图就漏。

3. **静态反抽无动态实证**(真机 e2e 截图 + 抓包)
   视觉 drift(CloseX 左上还是右上、横滑还是多列、单选还是多选)与协议 drift(流式请求是否真跑通、真响应字段是否齐)静态看不出。DTO 里的字段名不等于真响应——弱类型/late 字段缺值不报错,必须抓一次真包对照。

4. **缺跨端能力探针 spike**
   新平台的布局语义 / 状态机 / 渲染限制 ≠ 旧平台假设。把「整页容器 + 安全区 + 顶栏」机械翻译成整页 padding,会导致首项位置、右侧溢出、底部固定按钮全错;跨渲染上下文的父子状态联动、runtime 主题选择器、覆盖层弹窗等,不先做能力探针就会踩平台限制。

5. **已有新平台代码被误当真值基线**
   它可能只是早期半成品。在「结构或状态机与源不一致」的代码上继续堆补丁,等于把差异隐藏到后续状态里,越补越发散。

6. **dark/light 未成为提交前强制验收项**
   图片资源、背景色、文字色、图标 tint、禁用态都可能双模式不同。单模式通过 ≠ 1:1。

7. **验证过晚,依赖用户肉眼**
   应在提交前按矩阵自检,而不是安装后等用户逐项报 drift。

8. **AMENDMENTS 累加但不沉淀 retrospective**
   同样的漏抽跨模块复发,没有把「反抽应查哪些维度」固化成 gate。

## ✅ 正确

**核心**:反抽源实现时,把「静态 grep 采样」升级为「完整深读 + 三类实证(真机 e2e / 抓包 / 跨端能力探针)+ 提交前证据 gate」。宁可反抽多花时间(如 grep 30min → 全 Read + 截图 + 抓包 ~1.5-2h),换 1 轮收敛。

反抽完整性四阶段:

1. **全文件深 Read + 调用图**:不止读组件定义,读所有调用方函数体、入口 handler、条件分支、传入参数;逐字抄文案,不凭印象转述。
2. **动态实证**:真机 e2e 走一遍截图作 baseline(视觉);抓一次真请求/真响应对照 DTO(协议)——不能只信字段名。
3. **跨端能力探针**:对新平台不确定的机制(布局语义 / 跨上下文状态 / runtime 主题 / 弹窗层级)先做最小 spike 验证再派单,别把旧平台假设直接翻译。
4. **retrospective 沉淀**:每轮 AMENDMENTS 收敛成「反抽应查维度」gate,阻止同类 drift 跨模块复发。

### UI 还原一轮交付 gate(UI 类任务专用,折叠自某工程约束)

UI 还原任务在上述基础上,提交前必过五道 gate:

- **Gate 1 — 源全真值 sweep**:实施前产出真值表,每项标 `源文件:行号`,覆盖六维:
  - 节点:page / widget / view / dialog / bottom sheet / report / empty / loading / error
  - 数值:padding / margin / font / radius / height / width / aspectRatio / duration
  - 资源:image / icon / lottie / color token / dark variant / string
  - 行为:click / route / enable / disable / selected / final step / back / submit / toast
  - 数据:endpoint / request / response DTO / cache / default value
  - 主题:light / dark color / image / tint / disabled / pressed
- **Gate 2 — 新平台现状审计**:先判已有代码属于 `可复用`(结构行为均对位,只补参数)/ `可扩展`(主结构可用,需扩 prop/state/资源)/ `不可作真值`(结构或状态机不同,须重构重写)。**禁止在「不可作真值」的代码上继续堆补丁**。
- **Gate 3 — 分层实施顺序**:资源与 color token(base/dark)→ 公共组件/页面内 builder → 静态布局 → 状态与交互 → 路由/弹窗/完成页/报告页 → 边界态与异常态。禁止跳序边看边补。
- **Gate 4 — dark/light 双模式验收矩阵**:首屏 / 选中态 / 禁用态·空态·loading / 弹窗·bottom sheet / 完成页·最后一步·报告页 / 状态栏·底部安全区 / 图片资源·icon tint —— 每项 light 与 dark 都必测。单模式通过不算过。
- **Gate 5 — 提交前证据**:handoff / 最终说明必含 ① 源真值文件与关键行号 ② 新平台修改文件清单 ③ light/dark 验收结果 ④ 构建命令与结果 ⑤ 真机安装验证结果或未验证原因。

## lint 状态

- ⏳ 静态难全查(反抽完整性是协调端判断类)→ 落地为 task md / handoff baseline hook 的段标 gate:
  - task md 若涉及 UI 还原 / 流式协议 / 复杂弹窗 / 状态机 → 真值文档缺任一必查段(节点/数值/资源/行为/数据/主题)则拒发。
  - handoff 模板强制含 dark/light 验收矩阵 + 提交前证据五项。
  - Dev 端约束:UI task 未列「源文件:行号」+ 双模式验证,禁止提交。
  - 协调端 review:缺 Gate 1-5 任一项,不合并。
- 关联:反抽必读源码不信推测(某工程约束)、单状态截图误判 sticky/scroll(反模式 0141)、scaffold 已抽业务层散落直调底层 API(反模式 0097)。
