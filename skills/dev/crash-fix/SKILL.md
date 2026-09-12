---
name: crash-fix
description: 崩溃修复 / 闪退排查 / 编译错误 / ANR / 看堆栈 / fix crash / debug crash — 自动拉取崩溃日志或编译错误,4 阶段诊断(症状→根因→排除→修复),定位责任 Dev,执行修复。当用户说"App 闪退""崩溃""crash""compile error""编译失败""ANR / EXC_BAD_ACCESS""看一下崩溃日志""修一下这个错误"、提供堆栈或错误信息时自动触发。stack 中性 — 日志命令 / 编译命令 / 崩溃模式表从 references/{stack}.md 读。
user-invocable: true
---

# 崩溃快速修复

自动拉崩溃日志,诊断根因,定位责任 Dev,执行修复。

**stack 决定后必先 Read 对应 references**:

| Frontend stack | 必 Read |
|---|---|
| `mobile-android` | `references/android.md` |
| `mobile-ios` | `references/ios.md` |
| `mobile-flutter` | `references/flutter.md` |
| `mobile-harmony` | `references/harmony.md` |

---

## §1 思考模式(强制)

**执行 `/crash-fix` 时必须启用 think hard 深度思考**。崩溃诊断易被表面症状误导,必用结构化思考找根因:

```
think hard。

角色:资深移动端调试工程师(stack 见 references)

执行流程(4 阶段):

阶段 1【症状提取】
  - 异常类型、崩溃位置(文件:行号)、调用链、线程
  - 触发场景(哪个 View / Activity → Store / Feature → Action)

阶段 2【根因列举】
  - 列出至少 3 个可能的根因,按概率排序
  - 区分:代码逻辑错误 / 配置错误 / 依赖缺失 / 时序问题 / 内存问题 / 主线程违规
  - stack 特定崩溃模式见 references/{stack}.md §2

阶段 3【根因排除】
  - 通过 git log / blame 验证最近改动是否相关
  - 通过现有代码反推:哪些地方会触发这个异常
  - 排除最不可能的根因

阶段 4【修复方案】
  - 给出最小改动方案
  - 自我批判:这个修复会不会引入新问题?是否治标不治本?
  - 确认无误后执行
```

---

## §2 启动方式

用户输入 `/crash-fix` 后,询问崩溃来源(选项因 stack 不同):

通用类目:
- **runtime**(运行时崩溃)— 从设备 / 模拟器拉
- **build** — 编译错误
- **paste** — 用户粘贴日志
- **crashlytics** — Firebase Crashlytics 报告
- **anr**(Android)/ **hang**(iOS / Harmony)/ **frame drop**(Flutter)— 无响应类

具体命令见 references/{stack}.md §1。

---

## §3 Step 1:自动拉日志

按 references/{stack}.md §1 的命令拉:

- **runtime**:拉最近 fatal exception(stack 的 log 系统)
- **build**:跑编译命令并 grep error
- **设备信息**:自动采集型号 / 系统版本 / App 版本

将拉到的关键日志摘要放到本对话上下文,完整原文归档到 `.ai-workspace/diag/{date}-crash-{slug}.log`。

---

## §4 Step 2:诊断根因

拿到日志后,按以下顺序分析:

### §4.1 提取关键信息

从崩溃堆栈 / 编译错误中提取:

- 异常类型(stack 特定见 references/{stack}.md §2 "常见崩溃模式" 表)
- 崩溃位置(文件名:行号)
- 调用链(从 App 代码到崩溃点的路径)
- 触发场景(哪个 view → state machine → action)
- 线程信息(主线程 / 后台 / async)

### §4.2 查找相关代码

```bash
# 根据崩溃文件名查找源码(stack 特定扩展名 / 路径前缀见 references)
find <source-root> -name "{崩溃文件名}.{ext}" -type f

# 查看崩溃行号附近代码
sed -n '{行号-10},{行号+10}p' {文件路径}

# 查看该文件最近的修改
git log --oneline -5 -- {文件路径}
git blame -L {行号-5},{行号+5} {文件路径}
```

### §4.3 分析架构链路

按 stack 特定的架构模式诊断(MVI / TCA / Riverpod / ArkUI):

- 检查状态机分支是否覆盖完整
- 检查 unsafe cast / 强解包 / 类型转换
- 检查 effect / async 操作的错误处理
- 检查依赖注入是否完整

详 references/{stack}.md §3。

### §4.4 生成诊断报告

```
崩溃类型:{异常类型}
崩溃位置:{文件:行号}
触发场景:{View / Activity} → {Store / Feature} → {Action}
线程:{主线程 / 后台}
根因分析:{一句话描述}
关联文件:{相关文件列表}
最近修改者:{git blame 结果}
```

---

## §5 Step 3:定位责任 Dev

根据崩溃文件路径自动判断责任 Dev。**项目特定 mapping 在 `<docs-hub>/page-owner-map.yaml`(若存在)** 或 `.sulde-config.yaml: team[].frontend / .modules`(若项目登记)。stack 特定模块路径前缀见 references/{stack}.md §4。

崩溃涉及多个模块时,优先按崩溃点(顶层堆栈帧)判断。

---

## §6 Step 4:执行修复

确认诊断后,自动切换到对应分支执行修复:

```
当前身份:{开发者姓名}({git alias})
当前分支:dev/{用户名}/fix-{模块名}
崩溃位置:{文件:行号}
修复方案:{具体修改描述}
```

### §6.1 修复原则

1. **最小改动**:只修崩溃点,不顺带重构
2. **防御性修复**:加空值检查 / guard / 边界检查 / 类型守卫,**不假设上游正确**
3. **主线程保护**:UI 操作确保主线程(stack 特定见 references)
4. **保留现场**:修复前先记录崩溃复现条件到 `.ai-workspace/diag/`
5. **验证编译**:修复后跑 stack 编译命令(见 references)确认编译通过
6. **提交由 Agent 完成**:验证与报告通过后按 §7 提交；若发现超出原任务的语义选择或高风险效果，先走宿主原生 Allow/Deny，不让用户代跑 Git

### §6.2 验证(必跑)

跑 stack-specific 验证(`/assign` skill §5 verify strict):
1. 重新 build → exit 0
2. install → exit 0
3. launch → 触达原崩溃场景 → 不再 crash
4. 抓 log 30s → 无新 crash / fatal

详 references/{stack}.md §5。

### §6.3 崩溃报告归档

写入 `.ai-workspace/diag/{date}-crash-{slug}-report.md`:

```markdown
# 崩溃报告

时间:{时间}
设备:{stack 特定型号 / 系统版本}
App 版本:{版本}

## 崩溃堆栈

{原始日志}

## 诊断

- 类型:{异常类型}
- 位置:{文件:行号}
- 线程:{主线程 / 后台}
- 根因:{描述}
- 责任:{Dev X}

## 修复

- 分支:{分支名}
- 改动:{文件列表}
- 方案:{修复描述}

## 验证

- Build: ✅ / ❌
- Install: ✅ / ❌
- Re-run scenario: ✅ no crash / ❌ still crash
- 30s log scan: ✅ clean / ❌ new errors
```

---

## §7 与 /postmortem 衔接

崩溃修复完工后(commit 前)**必跑 `/postmortem`** skill,走 4 问漏斗:

- Q1 以前踩过这个 pattern 吗?(grep 反模式集合)
- Q2 会再踩吗?
- Q3 能不能 lint 化?
- Q4 其他 frontend 也有吗?

详 `postmortem` SKILL。修复 + /postmortem 通过后才 commit。

---

## §8 示例

```
用户:/crash-fix
助手:崩溃来源?(runtime / build / paste / crashlytics)
用户:runtime
助手:正在拉取日志...

[自动执行,stack-specific 命令见 references]
1. 拉 log → 发现 {异常类型} at {文件}:{行号}
2. 读取代码 → 定位根因
3. git blame → 最近由 {Dev X} 修改
4. 判断:{模块} → {Dev X}
5. 生成修复方案

诊断完成:
  崩溃:{文件}:{行号} {异常类型}
  根因:{一句话}
  修复:{方案}
  责任:{Dev X}

task 已授权且根因明确 → Agent 直接实施并验证。
若存在多个会改变产品语义的方案或新增高风险效果 → 展示宿主原生 Allow/Deny 决策卡，Allow 后由 Agent 继续执行；不要求输入 `y/n`、固定短语或命令。
```
