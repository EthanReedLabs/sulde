# 第三方软件与模型

[English](THIRD_PARTY_NOTICES.md) | **简体中文**

本清单说明 Sulde 源码和初始化脚本引用的外部组件。项目 [LICENSE](LICENSE) 与
[NOTICE](NOTICE) 适用于项目自有材料，不替代这些组件自身的条款。
以下上游声明的核对日期为 **2026-09-13**。

## 分发范围

源码打包流程携带 Sulde 代码、文档和空知识容器，不在插件产物内安装 Python 包或下载
模型权重。初始化脚本另行安装依赖、下载模型到用户的数据环境。Claude Code 与 Codex
是独立宿主产品，其可执行文件不包含在插件内。

本文是源码依赖清单，**不是已解析的完整 SBOM，也不是离线分发所需的全部通知文件**。
实际版本、递归依赖、模型转换件及二进制内容取决于具体环境。表中的上游许可不能证明
所有同名历史版本或下载件均适用相同条款。

## Python 依赖

下列源码路径均相对于 Sulde 仓库。初始化脚本为 `scripts/kb/bootstrap.sh`；
相关导入也见于 `tools/kb-index/` 和 `scripts/kb/`。

| 组件 | 用途与声明 | 上游许可来源 |
| --- | --- | --- |
| PyYAML | YAML 解析；`hooks/requirements.txt` 声明 `pyyaml>=6.0`；初始化安装 `pyyaml` | [MIT — PyYAML](https://github.com/yaml/pyyaml/blob/main/LICENSE) |
| FastEmbed | 向量嵌入与重排；初始化安装 `fastembed` | [Apache-2.0 — FastEmbed](https://github.com/qdrant/fastembed/blob/main/LICENSE) |
| jieba | 中文分词；初始化安装 `jieba` | [MIT — jieba](https://github.com/fxsjy/jieba/blob/master/LICENSE) |
| cryptography | `scripts/kb/mem-sync.py` 使用的加密能力；初始化安装 `cryptography` | [Apache-2.0 OR BSD-3-Clause — cryptography](https://github.com/pyca/cryptography/blob/main/LICENSE) |
| NumPy | 检索与记忆模块的数值运算；由 FastEmbed 依赖环境供应 | [BSD-3-Clause — NumPy](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |

初始化脚本没有锁定精确包版本；已有环境通过导入检查时会被复用。因此这些声明不能
标识可复现的完整安装依赖集合。二进制 wheel 还可能携带其他组件、原生库及通知文件。

## 模型

| Sulde 使用的模型名 | 用途 | 原始上游声明 |
| --- | --- | --- |
| `BAAI/bge-small-zh-v1.5` | 中文文本向量嵌入 | [MIT — 原始模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5/blob/main/README.md) |
| `BAAI/bge-reranker-base` | 交叉编码器重排 | [MIT — 原始模型卡](https://huggingface.co/BAAI/bge-reranker-base/blob/main/README.md) |

FastEmbed 将模型名称解析为实际下载件。本仓库没有锁定转换仓库、revision 或权重哈希。
再分发权重前，应确认实际下载文件及其附带条款；原始模型卡不能单独充当转换产物的
完整许可清单。

## 再分发记录

仅分发源码插件时，将本清单与项目许可和通知文件一并保留。若向产物加入依赖、原生
二进制、字典或模型权重，应完成以下记录：

1. 记录准确组件版本、来源 URL、模型 revision、文件哈希和目标平台。
2. 从这些精确分发件中提取许可、版权和适用的 NOTICE，覆盖递归及内嵌组件，按条款携带所需通知。
3. 记录修改，并针对实际使用及分发方式核对兼容性。
4. 区分第三方权利、Sulde 非商业授权和历史 MIT / BSL 已授出的权利。

这些记录补充[许可说明](docs/LICENSING.zh-CN.md)。产品名仅用于标识集成点和来源，
不表示上游认可 Sulde，或相关产品归 Sulde 所有。
