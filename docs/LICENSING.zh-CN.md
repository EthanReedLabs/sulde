# 许可与使用边界 / Licensing guide

[English](LICENSING.md) | **简体中文**

Sulde 当前源码采用 **PolyForm Noncommercial License 1.0.0**，SPDX 标识为
`PolyForm-Noncommercial-1.0.0`。商业用途不在本次许可授权范围内。
完整条款见 [LICENSE](../LICENSE)，版权与来源见 [NOTICE](../NOTICE)。
本文为使用说明，具体授权以英文许可证原文为准，不增加、删减或替代其条款。

## 可以做什么

- 为没有预期商业应用的个人学习、实验、研究和兴趣项目使用 Sulde。
- 在许可证允许的目的下阅读、复制、修改源码，维护 fork，并分享修改版本。
- 提交问题、文档修正和代码贡献；贡献规则见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

标准许可证的 `Noncommercial Organizations` 条款还明确许可慈善组织、教育机构、
公共研究机构、公共安全或卫生组织、环保组织及政府机构使用，不受其资金来源或
资金义务影响。这里保留该标准条款，不能把它解释为“任何组织使用都禁止”。

## 商业使用边界

对未落入许可证明确允许范围的商业用途，以下行为不获本许可证授权：

| 场景 | 当前许可 |
| --- | --- |
| 出售、付费分发 Sulde 或基于其源码修改的产品 | 不授权 |
| 将 Sulde 包装为收费插件、SaaS、托管服务或商业产品的一部分 | 不授权 |
| 在企业内部使用 Sulde 支撑商业研发、生产或经营 | 不授权；内部自用并非豁免 |
| 使用 Sulde 完成收费外包、客户交付或商业咨询工作 | 不授权 |
| 免费提供 Sulde 服务，用于商业引流、广告收入或商业产品推广 | 不因免费而获得授权 |

判断取决于使用目的和许可证的明确许可，不仅取决于是否单独收取插件费用。
个人账号、私有 fork、只在公司内部运行或公开修改源码，都不会自动取得商用权。
本仓库不提供商业授权，也不承诺会另行提供；许可问题可联系
[eric.gao.tech@gmail.com](mailto:eric.gao.tech@gmail.com)。

## 转载、修改与再分发

接收任何部分源码的人必须同时获得许可证全文或其官方 URL，以及项目提供的全部
`Required Notice:` 声明。建议原样附带 `LICENSE` 和 `NOTICE`，标明修改与来源，
并保留适用的第三方许可及版权声明。Fork 或重新打包不会取消原有许可限制。

项目许可适用于项目自有的代码、脚本、hooks、skills、模板和文档，另有明确许可
的材料除外。第三方依赖、下载的模型及外部宿主/API 服务分别遵守自身条款。
本许可不主张用户独立编写的项目代码或知识内容的所有权；包含或改编 Sulde 内容
的材料仍需遵守适用条款。独立产物的归属也不等于获准商业使用 Sulde 工具本身。

## 为什么称为源码可见

[OSI 开源定义第 6 条](https://opensource.org/osd)要求不得限制商业等应用领域。
因此这里使用“源码可见 / source available、仅限非商业用途”的表述，避免把
禁止商用的许可误称为 OSI 意义上的开源。源码公开不等于任意用途免费授权。

## License history

此次切换以**包含本许可变更的源码修订**为界；不得仅凭复用的插件版本号判断许可。
接收者应查看具体提交、发行包内的 `LICENSE` 和相应声明。

| 范围 | 适用说明 |
| --- | --- |
| 历史 v0.1.x | 已授出的 MIT 权利继续有效，见 [MIT 存档](../LICENSE-v0.1.0-MIT-archive) |
| 此次切换前已按 BSL 1.1 分发的副本 | 原有 BSL 条件及转 MIT 权利继续有效，见 [原声明存档](../LICENSE-BSL-1.1-archive) |
| 首次按当前许可分发的新内容 | PolyForm Noncommercial 1.0.0；没有自动转 MIT 的日期 |

新的许可声明不撤销或缩减历史版本及其内容已经授出的权利，也不把第三方或历史
贡献者未授权重许可的内容强行改为新许可。使用历史内容可依其原有授权；使用包含
新内容的版本需同时满足相应许可。历史存档不构成新内容的 MIT/BSL 双重许可选项。

## 官方依据

- [PolyForm Noncommercial 1.0.0 原文](https://polyformproject.org/licenses/noncommercial/1.0.0)
- [SPDX 许可证标识](https://spdx.org/licenses/PolyForm-Noncommercial-1.0.0.html)
- [历史 BSL 1.1 原文](https://mariadb.com/bsl11/)
