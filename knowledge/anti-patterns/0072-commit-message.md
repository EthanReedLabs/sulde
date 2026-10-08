---
doc_id: "ap-0072"
container: anti-patterns
platform: none
summary: "0072 commit message 用英文"
---

# 0072 commit message 用英文

- **平台**:双端
- **复发次数**:0

## ❌ 错误

```
git commit -m "feat: implement home vertical swipe"
```

## ✅ 正确

```
git commit -m "feat: 基于 ViewPager2 实现首页全屏竖滑容器"
```

（commit message 用中文,与本地工程师习惯一致,避免对外审查时显出工具痕迹。）
