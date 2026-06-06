# LegadoHub 会话汇总 2026-06-05

## 项目定位

项目名：LegadoHub

项目目录：

`C:/Home/Workspace/UGit/legado-hub`

目标是做一个面向阅读/Legado APP 的本地书源聚合中间层。阅读端最终只导入一个 LegadoHub 生成的聚合书源；搜索、详情、目录、正文、缓存、追更、书源治理和后续 AI 校对都由本地服务处理。

当前执行形态优先 Windows 本地脚本运行，Docker 放到后期。

## 角色分工

- Codex：规划、规则整理、代码审查、验收标准、验收审核。
- Kimi：具体实现、文件修改、运行验证、阶段交付。
- 后续 `/goal` 不再单独建文档，只在会话回复里用 `text` 代码块给一行命令。
- `docs/execution-rules.md` 已记录该协作规则。

## 已确认技术方向

- 后端：Python + FastAPI。
- 存储：早期使用 SQLite。
- 阅读书源解析：不直接搬 Android/Kotlin 引擎，先用 Python 自研统一解析引擎。
- `Luoyacheng/legado` 作为阅读规则语义参考。
- `freeok/so-novel` 作为规则模型、站点适配、聚合搜索参考。
- 阶段 2 开始同步建立后端 Web 调试界面，用于搜索、展示书籍、查看目录和正文。

## 已建立的重要文档

- `docs/project-plan.md`
  - 总体规划、阶段划分、功能列表。
- `docs/execution-rules.md`
  - Codex/Kimi 分工、质量门禁、goal 写法。
- `docs/implementation-plan-phase-1.md`
  - 阶段 1 给 Kimi 的完整实现计划和 AI 自测步骤。
- `docs/upstream-sources.md`
  - 上游仓库和网站来源说明。
- `docs/raw-source-archive.md`
  - 原始书源归档目录、统计、来源、复跑命令。
- `docs/reference-aggregate-source.md`
  - 用户提供的聚合书源样本说明。
- `docs/skills/book-source-craft/SKILL.md`
  - 用于后续生成阅读书源的项目内 skill 草案。

## 阶段 1 当前状态

Kimi 那边正在或已经按阶段 1 goal 执行。当前规划要求阶段 1 实现：

- FastAPI 骨架。
- `start.bat` Windows 启动脚本。
- SQLite 初始化。
- `/health`
- `/api/info`
- `generated/legadohub-source.json`
- `/api/legado/source`
- 占位接口：
  - `/api/legado/search`
  - `/api/legado/book/{book_id}`
  - `/api/legado/book/{book_id}/toc`
  - `/api/legado/chapter/{chapter_id}`

阶段 1 验收要看 Kimi 返回的：

- 文件变更清单。
- 依赖变化。
- 实际运行命令。
- 测试结果。
- `/health`、`/api/info`、`/api/legado/source` 输出。
- 占位 API 输出。
- `inspect_legado_source.py generated/legadohub-source.json` 输出。
- 未解决问题。

## 书源归档状态

已新增可复跑采集脚本：

`scripts/collect_source_archives.py`

复跑命令：

```powershell
python scripts/collect_source_archives.py --clean
```

输出目录：

- `data/sources/raw/by-site/legado/`
- `data/sources/raw/by-site/so-novel/`
- `data/sources/raw/rule-packs/`
- `data/sources/raw/upstream-metadata/`
- `data/sources/raw/manifest.json`

当前采集统计：

- Legado 站点文件：2307 个。
- Legado 原始书源对象：6170 条。
- So Novel 站点文件：25 个。
- So Novel 原始规则对象：25 条。
- 规则包：1 个。
- 上游元数据文件：1 个。
- `data/sources/raw/` 含 `manifest.json` 后总文件数：2335 个。

注意：2335 是文件数，不是书源对象数。当前策略是“一个网站/域名一个文件”，多个来源里同域名的不同规则会合并到同一个 JSON 数组。

## 已纳入来源

### XIU2/Yuedu

- 本地：`work/XIU2-Yuedu/shuyuan`
- 远程：`https://raw.githubusercontent.com/XIU2/Yuedu/master/shuyuan`
- 当前确认本地与远程各 26 条。
- 已合并进 `data/sources/raw/by-site/legado/`。

### aoaostar/legado

- 本地：`work/aoaostar-legado/sources/*.json`
- 本地：`work/aoaostar-legado/sources/*.zip`
- 已合并进 `data/sources/raw/by-site/legado/`。

### Yiove 综合书源库

用户指出的页面：

`https://shuyuan.yiove.com/book-source-collections?page=1&page_size=20`

该地址是 SPA 前端路由，直接请求会返回 HTML。已从前端 chunk 中确认真实 API：

- API base：`https://shuyuan-api.yiove.com`
- 合集列表：`/shuyuan/book-source-collections?page=1&page_size=100`
- 合集导入：`/import/book-source-collection/{collection_id}`

当前只抓取了 2026 年更新的 Yiove 书源合集，没有抓 Yiove 全量 31135 个单条书源列表。用户明确说“这个先不抓”。

当前纳入 2026 年合集：

- `墨辰整理书源大全7.1（禁止倒卖）`：459 条。
- `一些皇叔书源`：168 条。
- `明月照大江书源合集`：424 条。
- `一程书源合集`：65 条。
- `25 个优质书源`：25 条。
- `墨辰整理书源大全7.0（禁止倒卖）`：424 条。

合集元数据：

`data/sources/raw/upstream-metadata/yiove-2026-book-source-collections.json`

### freeok/so-novel

- 本地：`work/freeok-so-novel/bundle/rules/*.json`
- 远程：`https://raw.githubusercontent.com/freeok/so-novel/main/bundle/rules/main.json`
- 已按 `url` 域名拆分到 `data/sources/raw/by-site/so-novel/`。

### sjshb57/legado-57

- 本地：`work/sjshb57-legado-57/v2.8.6.json`
- 该文件是净化/替换规则，不是站点书源。
- 已放到 `data/sources/raw/rule-packs/sjshb57-legado-57-v2.8.6.json`。

## 暂未抓取或不应抓取

- Yiove 单条书源全量列表：暂不抓，用户已明确说“这个先不抓”。
- `Luoyacheng/legado`：是阅读 APP 本体和解析引擎参考，不是书源包。
- Docker：后期做。
- 完整 Web 管理台：阶段 6 做；阶段 2 先做后端 Web 调试/浏览界面。

## 已跑验证

脚本语法：

```powershell
python -m py_compile scripts/collect_source_archives.py
```

全量采集：

```powershell
python scripts/collect_source_archives.py --clean
```

一致性检查结果：

- `manifest.json` 可解析。
- Legado 磁盘文件数与 manifest 一致。
- So Novel 磁盘文件数与 manifest 一致。
- rule pack 文件数一致。
- upstream metadata 文件数一致。
- manifest 无重复输出路径。
- 最近一次采集无远程失败项。

## 新会话建议从这里开始

新会话工作目录建议直接进入：

`C:/Home/Workspace/UGit/legado-hub`

建议先读：

1. `docs/project-plan.md`
2. `docs/execution-rules.md`
3. `docs/raw-source-archive.md`
4. `docs/implementation-plan-phase-1.md`

如果 Kimi 已完成阶段 1，实现验收时先不要直接改代码。先按 Codex 职责审核：

- 对照 `docs/implementation-plan-phase-1.md` 检查功能是否覆盖。
- 核对 Kimi 提供的命令和输出。
- 本地复跑关键测试。
- 检查生成的 `generated/legadohub-source.json`。
- 确认占位 API 没有假装实现真实解析。

如果继续规划阶段 2，目标应聚焦：

- 从 `data/sources/raw/by-site/legado/` 选少量标准源。
- 实现阅读规则解析 MVP。
- 跑通搜索、详情、目录、正文。
- 同步做后端 Web 调试界面。
- 不要一开始全量加载 2307 个站点文件。
