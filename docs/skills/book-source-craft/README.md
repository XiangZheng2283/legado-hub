# Book Source Craft

这里是 LegadoHub 第三方书源插件的开发入口。权威契约只有一份：

- [书源插件协议](../../architecture/source-plugin-contract.zh-CN.md)

本文只说明执行顺序，不重复定义接口。

## 开发流程

1. 阅读协议，确认宿主与插件边界。
2. 从 [插件模板](references/source-plugin-template.zh-CN.md) 建立 `metadata.yaml`、`source.py`、`README.md` 和 `smoke/`。
3. 用真实书名、作者和真实 URL 验证 `search -> detail -> toc -> chapter`，先确认站点 API/AJAX/分页，再写选择器。
4. 保存完整 fixture；分页目录必须保存所有被访问的页面，并声明精确章节数、首尾章节、URL 唯一和连续 index。
5. 抽查首部、中部、尾部正文，检查乱码、分页、串章、挑战页和水印；繁体站同时验证输入转繁和输出转简。
6. 逐级探测并发和请求间隔，失败时再分别验证 stealth、代理和 browser，最后把实测结果写入 metadata。
7. 阶段结束后集中运行结构校验、fixture smoke 和真实链路；正式提交前运行仓库完整门禁。

## 必读参考

- [插件模板](references/source-plugin-template.zh-CN.md)：目录骨架和最小实现。
- [真实站点适配流程](references/plugin-source-workflow.md)：抓取、解析和定位问题的顺序。
- [聚合源模式](references/aggregate-source-pattern.md)：仅用于理解宿主聚合边界，插件不得自行聚合。
- [公开书源参考](references/public-source-references.md)：用于发现站点规律，不作为可用性证据。
- [正式化检查](references/stage-2-plugin-production.md)：历史补充材料；与协议冲突时以协议为准。

## 完成定义

一个插件只有在以下结果都明确时才算完成：

- 静态契约通过。
- 完整 fixture smoke 通过。
- 真实搜索与真实读取链路通过，或分别标记具体未评估/环境受阻项。
- 详情字段、完整目录、三处正文、编码、繁简、代理/browser 和限流均有证据。
- 版本与 README 已更新。

站点更新慢不等于插件失败；搜索失败也不等于详情、目录和正文全部失败。报告必须把这些情况分开。
