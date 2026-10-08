---
doc_id: "ap-0188"
container: anti-patterns
platform: cross
summary: "子构建里某工具变量为 NOTFOUND 却照样跑完并产出空产物,失败拖到主工程链接期才报符号缺失/文件无效"
sedimented_by: auto
---

# 0188 — ExternalProject 子构建不继承工具链,工具 NOTFOUND 静默产出空产物

- **平台**:跨平台(CMake / 含 ExternalProject、子构建的构建系统通用)

## ❌ 错误

用 `ExternalProject_Add`(或等价的子构建机制)引入外部工程,默认假设子构建
会继承父工程的 `CMAKE_MAKE_PROGRAM`、编译器与工具路径(如着色器编译器
`glslc`)。子构建独立 configure 时工具解析为 `NOTFOUND`,生成器把对应命令
吞掉或跑出错误产物,构建仍报"成功"并落下**空的中间产物**(空 .a/空生成文件),
直到主工程链接期才以符号缺失、文件格式无效等形式暴露。

## 为什么

ExternalProject 的子构建是**独立的 CMake configure/build 进程**,不继承父
工程缓存变量——父工程里找到的工具路径对子构建不可见,子构建按自己的环境
重新查找,查不到就是 `NOTFOUND`。而部分生成器/自定义命令对 NOTFOUND 工具
不硬失败(命令展开为无效调用被吞、或规则跳过),产出空文件也算"目标已生成"。
错误因此跨越两道边界延迟暴露:子构建→主构建、编译期→链接期,报错位置离
根因极远,极易误诊为链接配置问题。

## ✅ 正确

- **显式透传工具链**:`ExternalProject_Add` 的 `CMAKE_ARGS` 里显式传
  `-DCMAKE_MAKE_PROGRAM=...`、编译器与关键工具路径(或统一传
  `CMAKE_TOOLCHAIN_FILE`),不依赖隐式继承
- **尽早硬校验工具**:configure 阶段对关键工具变量断言非 NOTFOUND
  (`if(NOT TOOL_X) message(FATAL_ERROR ...)`),把失败从链接期拉回配置期
- **校验中间产物非空**:子构建产物接入主工程前加一步存在性+非零大小检查
  (自定义命令/脚本断言),空产物立即失败而非流入链接
