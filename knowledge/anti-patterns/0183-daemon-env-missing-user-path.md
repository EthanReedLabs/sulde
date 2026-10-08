---
doc_id: ap-0183
container: anti-patterns
platform: none
summary: 定时任务/守护进程里调用的 CLI 手动跑正常,由 launchd/cron 触发时报 command not found 或静默无产出
related: ["ap-0225"]
---

# 0183 — 守护进程环境缺用户级 PATH,调不到用户安装的 CLI

- **平台**:macOS launchd / Linux cron 通用

## ❌ 错误

LaunchAgent plist(或 crontab)的 ProgramArguments 直接调用用户级安装的 CLI
(如 `~/.local/bin`、`/opt/homebrew/bin` 下的工具),假设它继承交互 shell 的 PATH。

## 为什么

launchd/cron 以**最小环境**启动进程:PATH 通常只有 `/usr/bin:/bin:/usr/sbin:/sbin`,
不 source shell 配置文件——交互终端里"明明能跑"的命令,定时触发时 command not found。
更隐蔽的形态是脚本内部再调这些 CLI:外层脚本能启动,内层调用静默失败,
日志里只有一行不起眼的报错甚至什么都没有。

## ✅ 正确

- plist 的 `EnvironmentVariables` 显式声明 PATH,把用户级目录列全
  (`~/.local/bin:/usr/local/bin:/opt/homebrew/bin:` + 系统默认);
  或所有外部命令一律绝对路径调用
- 交付定时任务前,用 `env -i PATH=/usr/bin:/bin <脚本>` 模拟最小环境跑一次,
  别拿交互终端的成功当验证
