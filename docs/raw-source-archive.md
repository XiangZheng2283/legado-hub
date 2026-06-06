# 原始书源归档说明

本文记录 LegadoHub 当前已拉取到本地的公开书源与规则来源。归档目标是保留原始规则对象，方便后续订阅同步、健康检查、去重、清理和书源治理逐步接入。

当前路线已改为直接移植阅读内核。本文只描述历史归档数据，不再作为阶段一内核实现计划，也不再要求按站点文件作为核心书源模型。

## 目录结构

- `data/sources/raw/by-site/legado/`
  - 阅读/Legado 书源格式。
  - 一个站点或域名一个 JSON 文件。
  - 文件内容是该站点下的原始书源对象数组。
  - 这是历史归档形态，不是阶段一的内置源输入模型。
- `data/sources/raw/by-site/so-novel/`
  - `freeok/so-novel` 规则格式。
  - 一个站点或域名一个 JSON 文件。
  - 文件内容是该站点下的原始 So Novel 规则对象数组。
- `data/sources/raw/rule-packs/`
  - 非站点书源规则包。
  - 当前用于保存 `sjshb57/legado-57` 这类净化/替换规则。
- `data/sources/raw/upstream-metadata/`
  - 上游列表或集合元数据。
  - 当前保存 Yiove 2026 年更新的书源合集列表。
- `data/sources/raw/manifest.json`
  - 本次采集清单。
  - 记录来源状态、输出文件、格式、站点、数量和来源 ID。

## 当前统计

最近一次采集命令：

```powershell
python scripts/collect_source_archives.py --clean
```

采集结果：

- Legado 站点文件：2307 个。
- Legado 原始书源对象：6170 条。
- So Novel 站点文件：25 个。
- So Novel 原始规则对象：25 条。
- 非站点规则包：1 个。
- 上游元数据文件：1 个。
- 原始归档数据文件合计：2334 个。
- 加上 `manifest.json` 后，`data/sources/raw/` 下文件合计：2335 个。
- 归档目录当前总大小约 39 MB。

一致性检查结果：

- manifest 中 Legado 文件数与磁盘文件数一致。
- manifest 中 So Novel 文件数与磁盘文件数一致。
- manifest 中 rule pack 文件数与磁盘文件数一致。
- manifest 中 upstream metadata 文件数与磁盘文件数一致。
- manifest 内无重复输出路径。
- 最近一次采集无远程拉取失败项。

## 已纳入来源

### XIU2/Yuedu

- 本地来源：`work/XIU2-Yuedu/shuyuan`
- 在线来源：`https://raw.githubusercontent.com/XIU2/Yuedu/master/shuyuan`
- 格式：Legado 书源。
- 处理方式：读取后按 `bookSourceUrl` 域名拆分。
- 当前确认本地与在线来源各 26 条，去重后合并入 Legado 站点归档。

### aoaostar/legado

- 本地来源：`work/aoaostar-legado/sources/*.json`
- 本地来源：`work/aoaostar-legado/sources/*.zip`
- 格式：Legado 书源。
- 处理方式：读取 release 产物，去重后按 `bookSourceUrl` 域名拆分。

### freeok/so-novel

- 本地来源：
  - `work/freeok-so-novel/bundle/rules/main.json`
  - `work/freeok-so-novel/bundle/rules/proxy-required.json`
  - `work/freeok-so-novel/bundle/rules/rate-limit.json`
  - `work/freeok-so-novel/bundle/rules/no-search.json`
  - `work/freeok-so-novel/bundle/rules/cloudflare.json`
- 在线来源：`https://raw.githubusercontent.com/freeok/so-novel/main/bundle/rules/main.json`
- 格式：So Novel 自有规则。
- 处理方式：读取后按 `url` 域名拆分。

### sjshb57/legado-57

- 本地来源：`work/sjshb57-legado-57/v2.8.6.json`
- 格式：Legado 净化/替换规则，不是站点书源。
- 处理方式：归档到 `data/sources/raw/rule-packs/sjshb57-legado-57-v2.8.6.json`，不放入站点书源池。

### Yiove 综合书源库

- 页面入口：`https://shuyuan.yiove.com/`
- 真实 API：`https://shuyuan-api.yiove.com`
- 合集列表接口：`/shuyuan/book-source-collections?page=1&page_size=100`
- 合集导入接口：`/import/book-source-collection/{collection_id}`
- 格式：Legado 书源。
- 处理方式：筛选 `create_time` 位于 2026 年内的书源合集，逐个下载合集内容，再按 `bookSourceUrl` 域名拆分。
- 元数据归档：`data/sources/raw/upstream-metadata/yiove-2026-book-source-collections.json`

当前纳入 2026 年更新合集：

- `墨辰整理书源大全7.1（禁止倒卖）`：459 条，创建时间 2026-03-04。
- `一些皇叔书源`：168 条，创建时间 2026-02-15。
- `明月照大江书源合集`：424 条，创建时间 2026-02-11。
- `一程书源合集`：65 条，创建时间 2026-02-11。
- `25 个优质书源`：25 条，创建时间 2026-02-10。
- `墨辰整理书源大全7.0（禁止倒卖）`：424 条，创建时间 2026-01-04。

## 暂未纳入来源

### Luoyacheng/legado

- 这是阅读 APP 本体和原生解析引擎参考，不是公开书源包。
- 当前不纳入 `data/sources/raw/by-site`。
- 后续用于对照规则语义、解析能力和兼容性边界。

## 特殊文件

### `unknown.json`

路径：

`data/sources/raw/by-site/legado/unknown.json`

当前包含 99 条 Legado 书源对象。这些对象的 `bookSourceUrl` 不是标准域名或 URL，例如聚合说明、分类名、内部标记等。

处理原则：

- 暂时保留，避免丢弃可能有价值的规则。
- 阶段 2 不作为优先接入目标。
- 阶段 3 或阶段 5 做书源治理时，再按 `searchUrl`、`ruleBookInfo.tocUrl`、`ruleSearch.bookUrl` 等字段尝试反推真实站点。

## 采集脚本

脚本路径：

`scripts/collect_source_archives.py`

复跑命令：

```powershell
python scripts/collect_source_archives.py --clean
```

说明：

- `--clean` 只清理脚本管理的 `data/sources/raw/` 输出区。
- 不会删除 `data/sources/reference/光遇聚合26.6.2.json`。
- 不会修改上游克隆仓库。
- 会重新生成 `manifest.json`。

## 后续接入建议

阶段一只使用 `data/sources/raw/by-site/legado/sub-xiu2_yuedu.json` 验证 BookSource 导入和内核链路。其他归档文件在直接阅读内核稳定后再进入源治理和订阅同步流程。

后续接入时必须以单个 `BookSource` 对象为单位，身份使用 `bookSourceUrl`。不要再以站点文件名或域名聚合同站点多书源规则。
