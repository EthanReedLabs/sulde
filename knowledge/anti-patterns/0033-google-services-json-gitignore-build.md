---
doc_id: "ap-0033"
container: anti-patterns
platform: android
summary: "google-services.json 被 .gitignore 全量拦截导致 build 失败"
---

# 0033 — google-services.json 被 .gitignore 全量拦截导致 build 失败

- **平台**:Android（Firebase 集成）
- **复发次数**:0
- **lint 状态**:人工 review `.gitignore` 变更

## ❌ 错误

`.gitignore` 全量屏蔽 `google-services.json`（防 config 泄漏），导致：
- 开发端（clone 仓库后）`app/google-services.json` 不存在
- Firebase Gradle plugin 找不到配置文件 → build 失败（即使是 debug 包）
- 新成员加入项目 / CI 环境都卡在 build 阶段

## ✅ 正确

1. **提交占位配置**到 git（package_name 真实，其他字段 placeholder）：

```json
{
  "project_info": {
    "project_number": "000000000000",
    "project_id": "your-app-placeholder"
  },
  "client": [{
    "client_info": {
      "android_client_info": { "package_name": "com.example.app" }
    }
  }]
}
```

2. **`.gitignore` 放行 + 注释说明**：

```gitignore
# google-services.json：首版提交占位配置进 git（Firebase plugin 需要此文件才能 build）；
# 真实配置由甲方 / 运维获取后直接覆盖占位文件。
```

3. 真实配置到位后**直接覆盖占位文件**，不需改 .gitignore。

## 为什么错

- 秘密型配置（API key / 签名密钥）确实不应进 git，但 `google-services.json` 本质是"项目 ID + Firebase 服务地址"，不是真 secret
- build 依赖的配置文件全量 gitignore 会阻断协作
- 真要防泄漏：走 CI secret 注入而非 gitignore

## lint 状态

- ❌ 无法静态 lint，人工 review `.gitignore` 变更时注意"AI 痕迹文件"与"build 必需配置"的区别

## 关联

- 发版甲方提供材料清单 Firebase 项目真实配置段
