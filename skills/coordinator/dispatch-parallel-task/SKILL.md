---
name: dispatch-parallel-task
description: 协调端派发并行任务(≥2 个 task 给同端 Dev)的文件交集检查 + 宿主无关能力档矩阵规则。当用户说"并行派 X 个 task / Dev A 做这个 Dev B 做那个 / 多任务派单 / parallel-dev" 等触发词或协调端要写 2+ 并行 task md 时必 invoke。覆盖紧耦合识别 5 问 / 公共文件白名单 / Wizard 1 人 1 条线铁律 / 能力档分配矩阵。
user-invocable: true
---

# 协调端派发并行任务规则

> 真值来源:协调端规则 §派发并行任务前必做的文件交集检查 + §按矩阵标注能力档。

---

## §1 派发并行任务前必做的文件交集检查(强制)

**协调端负责任务规划,必须在给两端写 `/parallel-dev` 任务文件之前就做完文件交集检查**,不要把冲突风险推到两端执行时才发现。

**特别警觉**:同一物理 View/Activity 文件包揽多个 pageId(如 `<某列表 View>` 包含某主页面、子状态页与弹层)时,即使 task 名以 pageId 划分,**改动文件仍是同一个**,顶部/中部/底部 hunks 看似不同但 SwiftUI body / Reducer init / 顶层订阅块容易撞。审计时必须**深入到 hunk 区粒度**,不止文件粒度。

### 紧耦合识别清单(必查 5 问)

写 task 文件前,问自己 5 问:
1. 这几个 task **改不改同一个 View/Activity 文件**?(`grep -l '改动文件白名单' task-*.md`)
2. 即使改不同 hunks,**有没有共同基础设施**(单例订阅 / Reducer State init / Manifest 配置)?
3. **有依赖关系**的 task(如 T8 用 T7 的 currentlyPlayingTrackId)是否标了"必须串行"?
4. 单页有 ≥ 2 个 task 同时改 → 是否合并 task 文件?
5. **跨任务共享的资源**(如 token / drawable / scaffold)是否已先派出去当批 0?

### 紧耦合处理模板(发现紧耦合 → 4 选 1)

- **合并 task 文件**(2-3 task 内容塞 1 文件,Dev 一次粘 1 指令做完)
- **明确串行指令**("先做 T7 再做 T8 同分支",同 1 agent 接力)
- **拆 task 范围**(把共享 hunks 提到独立 base task,后续 task 各自只改自己 hunks)
- **派 1 个 agent 串行**(放弃部分并行优势,但避免合并冲突)

### 工作流

1. **先列出每个子任务的预计改动文件**(根据模块映射或 Grep 实际代码)
2. **两两做文件交集**:

   ```
   Android:
     Task A: feature-home/, core-ui/adaptive/
     Task B: feature-create/, core-ui/tokens/
     Task C: feature-profile/, core-ui/adaptive/   ← 与 A 冲突

   iOS:
     Task A: Sources/FeatureHome/, Sources/CoreUI/Adaptive/
     Task B: Sources/FeatureCreate/, Sources/CoreUI/Tokens/
     Task C: Sources/FeatureProfile/, Sources/CoreUI/Adaptive/   ← 与 A 冲突
   ```

3. **公共文件永远不并行改**:

   | 平台 | 禁止并行改的文件 |
   |---|---|
   | Android | `app/build.gradle.kts`, `settings.gradle.kts`, `core-ui/.../colors.xml`, `strings.xml`(values 主), `AdaptiveBaseActivity.kt`, `AppColors.kt`, `AppTypography.kt`, `AndroidManifest.xml` |
   | iOS | `<project>.xcodeproj/project.pbxproj`, `project.yml`, `Package.swift`, `AdaptiveScaffold.swift`, `AdaptiveLayout.swift`, `AppColors.swift`, `AppTypography.swift`, `Info.plist`, `Localizable.xcstrings`, `Sources/Spec/*` |

4. **发现交集 → 3 个选项**:
   - **拆任务(推荐)**:把共享文件的改动从一个任务里剥离,先让另一个人合并再拉新分支
   - **串行**:只派 2 个并行,第 3 个等前两个合并后再派
   - **合并**:让同一个人做所有触及共享文件的改动

5. **检查结果写进任务文件**:

   ```markdown
   ## 并行任务冲突检查(已确认)
   ✅ Task A × Task B:无交集
   ⚠️ Task A × Task C:Task C 已剥离对 AppColors.xml 的改动,留到 Task A 合并后
   ```

### 为什么在协调端做

两端 parallel-dev 的"第 0 步"是二次保险。**协调端做是第一道关**,两端做是第二道。协调端有全局视角(知道 Android 和 iOS 的对应任务是什么),能提前避开冲突;两端只看自己那个平台。

### 反例(真实踩坑)

| 错误 | 结果 |
|---|---|
| 派 3 个任务都改 `core-ui/` | merge Task 2 时冲突,merge Task 3 时冲突,每次都手动解 |
| 派 2 个任务都改 `project.pbxproj` | XcodeGen 自动生成的文件冲突几乎无法手动解,只能重新 xcodegen generate |
| 派 Dev A 做 Home, Dev C 做 Profile,两个都要改 `AppColors.kt` | 第一个合并后第二个必冲突,浪费 1 小时 |

### Wizard 类工作流 = 1 人 1 条线(强制)

**判定**:多页之间存在"上一步产出作为下一步输入"的链式依赖(如某多步骤创作流依次推进,每页扩中央 State/Feature)= Wizard 工作流。

**规则**:
- Wizard 工作流的**所有页面由单人串行完成**,不拆给多 Dev 并行
- 即使每页是独立 View/Fragment 文件,**中央 Store/Feature** 会被 N 人同时扩展 → 合并必冲突
- 其他 Dev 并发做**独立模块**(如某详情页 / 某独立弹层 / scaffold 补齐)

**反例**:曾尝试把某多步骤流程拆给 3 人,Dev A 做前段 / Dev B 做中段 / Dev C 做后段 — 三人都要改 `<某中央 Store>` / `<某中央 Feature>`,合并时连续冲突。

**正例**:Android Dev A 独占某多步骤流程 / Dev B 做独立详情页与弹层 / Dev C 做顶部栏 scaffold → 零中央文件冲突。

---

## §2 派发并行任务时按矩阵标注能力档

给两端终端写 `/parallel-dev` 任务文件时,**必须为每个子任务标注宿主无关的 `capability_tier`**；
目标 Claude Code/Codex session 再按当前宿主翻译，不能预写提供方型号或 thinking 语法。

### 子任务思考预算分配矩阵(与两端 parallel-dev skill 一致)

| 子任务类型 | `capability_tier` | Codex reasoning 最低线 |
|---|:---:|:---:|
| 架构搭建 / 跨模块重构 / Reducer 拆分 | **deep** | high |
| 复杂 Bug 修复 / 性能优化 | **deep** | high |
| 新 Feature 开发(含 State/Action/Reducer)| **balanced** | medium |
| UI 还原 / 列表页 / API 接入 | **balanced** | medium |
| 增删字段 / 配置修改 | **light** | low |
| 翻译补全 / 资源添加 / 编译错误修复 | **light** | low |

### 任务文件模板(必带能力档标注)

```markdown
### Dev A — {任务标题}
**capability_tier:{deep|balanced|light}**
**分支:dev/{用户名}/{模块名}**

{任务描述}
```

### 收益

矩阵的收益是把最低能力要求稳定留在 task 中，同时允许每个宿主按自己的模型目录和推理控制降本；
具体 token/价格不写死，避免宿主升级后数据失真。

### 检查清单(每次派发并行任务前)

- [ ] 每个子任务已按矩阵标注 `capability_tier`
- [ ] 没有把简单任务(翻译/编译修复)标成 `deep`
- [ ] 没有把架构改造标成 `light`
- [ ] 任务描述里说明了"是什么级别的复杂度"
