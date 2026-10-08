---
doc_id: "work-model/offline-fake-device-cli-testing"
container: work-model
platform: cross
summary: "无真机环境下用 PATH 前置 fake 设备 CLI + 环境变量命令覆盖点做离线自测,锁住设备流程编排逻辑防回退;一切 fake 桩(fake 设备 CLI / fake evaluator 等)输出必须与真实 schema 一致,否则 happy-path 自测掩盖真实门禁不可通过。"
related: ["work-model/verify-build"]
sedimented_by: auto
---

# 离线 fake 设备工具链 CLI 自测(无真机锁流程逻辑)

## 适用场景

设备流程脚本 / CLI(build → install → launch → 抓 log 等编排逻辑)需要回归保护,但当前环境或 CI 无真机 / 模拟器可连。

## 做法

1. **fake 设备 CLI(PATH shim)**:写与真实工具同名的 stub 脚本(如 `adb` / `hdc` / `devicectl`),放在 PATH 前部。stub 记录收到的完整参数到日志文件,并按预设场景返回固定输出与退出码,用来断言"编排逻辑调用了正确的子命令与参数序列"。
2. **命令覆盖点(环境变量)**:被测脚本把每个外部命令入口做成可覆盖的环境变量(如 `GRADLE_CMD`、`ADB_CMD`,默认指向真实命令),测试时指向 stub / 假命令,不修改被测脚本主体。每个外部命令入口都应有一个覆盖点。
3. **断言层**:对 stub 的调用日志做断言 —— 调用顺序、参数、次数;并让 stub 返回非零退出码 / 错误输出,覆盖失败分支(验证 abort / 重试 / 报错路径)。

## 边界

- 只能锁**流程编排逻辑**(顺序 / 参数 / 分支 / 错误处理),不能替代真机验证 —— 安装是否成功、渲染是否正确、是否崩溃仍需真机流程(见 [[work-model/verify-build]])。
- stub 的输出格式必须仿真实工具的关键行(如设备列举命令的表头 + 序列号行),否则被测脚本的解析逻辑测不真。
  - **补充(schema 一致性,通用化变体)**:此要求对一切 fake 桩通用,不限设备 CLI(fake evaluator、fake 校验器等同理)——桩的输出必须与真实实现的 schema 完全一致(字段名 / 嵌套结构 / 枚举值 / 退出码语义)。若桩按"理想化 schema"编造输出,happy-path 自测会全绿,而真实链路因 schema 不匹配根本过不了门禁——自测反而掩盖了问题。防御做法:桩上线前先抓一份真实输出作为模板逐字段对照,或让桩与真实实现共享同一份 schema 定义 / 校验器。

## 判定线

设备流程 CLI 含非平凡编排逻辑却无离线自测 = 回归无保护;外部命令入口硬编码、无覆盖点 = 不可测,应先引入覆盖点再补自测;fake 桩输出从未与真实输出逐字段对照过 = 该自测的绿灯不可信。
