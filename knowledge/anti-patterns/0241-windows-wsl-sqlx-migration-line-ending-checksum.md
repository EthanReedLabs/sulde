---
doc_id: "ap-0241"
container: anti-patterns
platform: cross
summary: "官方 Windows 构建能打开的既有 SQLite 状态库，换成 WSL/Linux 交叉构建的同源程序后却报历史 SQLx migration 已被修改，常见根因是 CRLF/LF 改变了迁移原始字节及其校验值。"
related: ["ap-0226"]
sedimentation_schema: 2
problem_type: host-inconsistency
evidence_status: verified
---

# 0241 — Windows 与 WSL 构建的迁移行尾不一致导致 SQLx 校验冲突

- **平台**：跨端（Windows 运行态 ↔ WSL/Linux 构建态）
- **复发次数**：1

## 问题原型

某程序的官方 Windows 构建已经创建并持续升级本地 SQLite 状态库。为了加入新功能，开发者
从相同上游版本或其后续提交在 WSL/Linux 中交叉构建 Windows 可执行文件。新程序一连接
旧库就报告某条历史 migration “previously applied but has been modified”，因而无法启动或
恢复会话；切回官方 Windows 程序又能正常工作。

期望是没有改动历史迁移 SQL 时，新构建可以沿用旧库并只追加新迁移。实际是 SQL 语义虽然
相同，迁移文件进入两个构建产物时的原始字节不同：Windows 发布链记录的是一种行尾，
WSL/Linux 构建嵌入的是另一种行尾，SQLx 因校验值变化而拒绝继续。

## ❌ 错误

1. 只比较 Git 提交、文本 diff 或 SQL 语义，看到“历史迁移没改”就断定数据库损坏。
2. 在 WSL/Linux 中直接交叉编译 Windows 程序，却不验证编译期嵌入的 migration 原始字节。
3. 为了让程序启动，直接删除状态库、修改 `_sqlx_migrations.checksum`，或把历史 migration
   改回“看起来正确”的文本。
4. 只验证 `--version`、编译成功或新建空库，不用上一版 Windows 真实升级路径的数据库
   快照做兼容测试。
5. 切回旧启动器后看到功能恢复就宣布修复；这种做法只是避开了不兼容的新构建，新功能和
   根因仍然存在。

## 根因与证据

SQLx 会把已执行 migration 的校验值记录在数据库中，校验对象是迁移内容的原始字节，而
不是 SQL 解析后的语义。`CRLF` 与 `LF` 对数据库执行效果可以完全相同，但 SHA-384 输入
不同，校验值也必然不同。

这类问题的关键不在于“哪一种行尾更正确”，而在于**后续构建必须复现已经投入使用的发布
链所记录的字节**。如果旧 Windows 发布链把 CRLF migration 嵌入程序并写入数据库，后续
WSL/Linux 构建就不能悄悄改用 LF；反过来也一样。

一次已验证实例形成了以下闭环证据：

- 旧库完整性检查为 `ok`，排除了普通 SQLite 损坏。
- 官方基线源码的历史 migration 在 SQL 语义上没有变化；逐条计算原始 LF 与 CRLF 版本
  的 SHA-384 后，数据库中全部已应用校验值只与 Windows 行尾版本一致。
- 未规范行尾的 WSL 交叉构建在数据库副本上稳定复现第一条 migration 校验失败。
- 将所有会被编译期嵌入的 migration 规范为既有 Windows 发布链的行尾后重新构建，同一
  数据库副本越过原失败点、成功追加后续 migration，完整性检查仍为 `ok`。
- 专项回归、状态诊断和真实启动链路均通过，证明修复没有依赖改写数据库校验表。

已排除的相似假设包括：历史 SQL 被业务改写、另一个进程篡改 migration 表、数据库页损坏，
以及仅由插件认证失败造成的启动告警。

## 适用边界

应当应用于同时满足以下条件的场景：

- migration 框架对历史迁移原始字节做强校验；
- 既有数据库由 Windows 发布件创建或升级；
- 新可执行文件来自 WSL/Linux、另一 checkout 或不同 Git 行尾策略；
- 官方程序可打开同一数据库，新构建却报告历史 migration 被修改。

不应直接应用于以下场景：

- 历史 migration 的 SQL 内容确实被修改；此时应恢复不可变历史并新增一条迁移。
- `quick_check`/`integrity_check` 已失败，或 migration 表存在来源不明的人工写入；应先按
  数据损坏或篡改处理。
- 两个构建产物嵌入的 migration 字节及其哈希已经证明完全一致；应继续检查框架版本、
  migration 集合和数据库身份。
- 框架明确对行尾做规范化后再校验；这时 CRLF/LF 不是有效根因。

插件 OAuth、网络失败或 MCP 服务自身退出可以与本问题同时出现，但它们不解释历史
migration checksum 冲突，必须单独分流。

## 判定样本

### 路由正例

- **输入**：官方 Windows CLI 能恢复旧会话，WSL 交叉构建的同源 Windows CLI 却报
  `migration was previously applied but has been modified`
- **预期**：apply
- **原因**：同时命中既有 Windows 数据库、跨宿主构建和历史迁移强校验三个必要条件
- **来源**：observed

### 路由反例

- **输入**：两个构建嵌入的 migration SHA-384 完全一致，但 SQLite `quick_check` 已报告
  数据页损坏
- **预期**：skip
- **原因**：行尾差异已经被证伪，现有证据指向数据库完整性故障
- **来源**：constructed

### 执行合格例

- **做法或输出**：先在线备份旧库，在副本上逐条比对数据库校验值与官方基线 migration
  的 LF/CRLF 原始字节哈希；只规范构建输入并重建，不改 checksum 表；最后用旧库副本和
  真实库分别验证迁移、完整性及实际启动链路
- **预期**：pass
- **原因**：根因证据、修复边界、数据保护、升级兼容和运行验收形成闭环
- **来源**：observed

### 执行失败例

- **做法或输出**：把启动器切回旧官方程序后确认能启动，但没有修复交叉构建产物，也没有
  在数据库副本上验证新程序
- **预期**：fail
- **原因**：只恢复了旧路径，新功能仍不可用，同一构建再次部署就会复发
- **来源**：observed

- **做法或输出**：直接修改 migration 元数据表中的历史 checksum 迎合新程序，看到进程
  启动就结束验收
- **预期**：fail
- **原因**：篡改了兼容性证据，既没有证明构建输入正确，也可能掩盖真实 SQL 内容漂移
- **来源**：constructed

## ✅ 正确

### 1. 先保护数据并建立双程序对照

- 使用 SQLite online backup API 创建一致性副本，不直接复制正在写入的数据库文件。
- 在同一副本上分别运行上一版官方程序和新构建，固定触发命令与环境。
- 先做 `quick_check`/`integrity_check`，把数据库损坏与 migration 兼容问题分开。

### 2. 比较原始字节，不比较“看起来一样”的文本

读取 `_sqlx_migrations` 中的版本与 checksum，再对官方基线的每一条已应用 migration 计算
候选字节哈希。至少同时检查仓库原始字节、统一 LF 和统一 CRLF 三种形态：

```python
raw = migration_path.read_bytes()
lf = raw.replace(b"\r\n", b"\n")
crlf = lf.replace(b"\n", b"\r\n")

for label, content in (("raw", raw), ("lf", lf), ("crlf", crlf)):
    print(label, hashlib.sha384(content).hexdigest())
```

必须逐条覆盖所有已应用 migration；只验证第一条只能证明复现点，不能证明整个升级链兼容。

### 3. 修构建输入，不篡改历史数据库

- 把既有发布链的 migration 字节定义为兼容基线。
- 在 checkout、打包或编译前对全部 migration 资源执行确定性行尾规范化；不要只处理本次
  新增文件，也不要按文件后缀白名单漏掉无后缀入口，相关收集盲区见 `ap-0226`。
- 用 `.gitattributes`、构建期规范化脚本或校验清单固定行尾；选择哪种行尾取决于既有发布
  基线，不应脱离存量数据库强推统一偏好。
- 历史 migration 一经发布保持不可变。需要改变 schema 或数据时，只新增 migration。
- 禁止通过更新 `_sqlx_migrations.checksum`、删除旧记录或重建用户数据库来“适配”产物。

### 4. 用旧库升级链验收

修复后的最低验收包括：

1. 新程序在旧库副本上越过原校验失败点。
2. 后续 migration 成功执行且记录为 success。
3. 数据库完整性仍为 `ok`，关键历史记录可读。
4. 与改动功能相关的专项测试通过。
5. 新程序在真实启动链路中完成一次最小 smoke；独立认证告警另行记录，不得混成迁移失败。
6. 部署采用新文件名并排放置，保留旧程序、启动器和数据库备份作为可审计回滚点。

## 消费与防复发

本条由 Windows 发布流水线、WSL/Linux 交叉构建脚本、数据库 migration review 和升级回归
共同消费。

可机械检查：

- 对已发布 migration 建立按版本排序的原始字节 checksum manifest，构建前逐条比对。
- CI 在 Windows 原生构建和 Linux/WSL 交叉构建之间比较嵌入资源的 checksum 清单。
- 每个发布候选必须用上一稳定 Windows 版本生成的数据库夹具运行升级测试，禁止只测空库。
- 扫描历史 migration 的内容 diff；发现修改立即失败，新增文件不受此规则阻断。

必须人工判断：

- 既有发布链究竟以哪组字节为兼容真值。
- checksum 不一致是否真的只有行尾差异，还是混入了 SQL 内容修改或错误基线。
- 真实用户数据的备份、迁移和回滚策略是否满足产品的数据风险等级。

## 关联

- `ap-0226`：两者都会让行尾处理在打包后才暴露，但 `ap-0226` 的根因是按扩展名筛选导致
  文件被漏处理；本条是 Windows 与 WSL/Linux 构建把同一 migration 转换成不同原始字节。
