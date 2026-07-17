# `/console` 能力审查与后续执行规划

> 状态：阶段 B-E 已完成
> 日期：2026-07-16
> 上位产品真相：`docs/PRODUCT.md`

## 1. 审查结论

当前问题不是“大量功能漏接”，而是三类状态混在了一起：

1. 已主动清理的旧页面和无实现控件仍留在旧设计稿或旧计划中。
2. 后端运维/外部契约没有前端页面，但本来就不要求有页面。
3. 少量真实缺口仍需修复，优先级高于继续追逐旧设计稿像素差异。

后续不恢复已删除的旧后台，不把每个后端路由都做成页面，也不继续把 `untitled/` 当成逐像素真相源。

## 2. 能力处置

### 2.1 保留并继续维护的产品闭环

- 登录与角色边界
- 搜索、订阅、共享书库、书籍详情、章节正文阅读
- 插件列表、启用/禁用、Ping 与运行错误
- 官方源登录、状态校验、注销与 Cookie 管理
- 运行参数、聚合策略、优先级与词库状态
- Reading/Legado 外部读取契约

### 2.2 已主动清理，不恢复

- `CachePage.tsx`、`VerificationPage.tsx`
- 旧 `Aggregate*` 页面体系；能力已合并到订阅/书库闭环
- `BookCard`、`SubscriptionCard`、`MasonryGrid` 旧组件方案
- 无实现的书源导入、书源删除、候选 Trace 操作按钮、书库筛选按钮
- AI 校对、改写、敏感词恢复及其章节详情字段
- 运行期 Smoke、verification、单书源 stage test 与插件 live-check；这些只属于插件编写期验证

章节详情中的只读 Trace 摘要属于运营证据，不是已移除的 Trace 操作，继续保留。

### 2.3 保留后端，不新增独立页面

- `/api/legado/*` 与 `/api/subscribe/legado/*`：外部读取契约
- `/api/console/cache*`：运维/恢复接口；不恢复旧 Cache 页面
- `/api/console/update-tasks*`、`/progress`、`/rule-engines`：后台调度与诊断
- 登录 debug trace：官方源登录诊断
- 用户管理 API：为多用户模型保留，Phase 1 前不新增管理页

### 2.4 删除候选

以下仅是前端内部封装，当前没有生产调用者。第一轮直接删除；未来出现真实 UI 时再按需添加：

- `reloadPlugins`、`batchDeletePlugins`、`testSource`
- `pluginAuth`、`pluginLogin`
- `searchJobs`、候选 verify/reviews/cancel 封装
- live-check、cache、verification、explore 封装
- 未使用的 library 日志/设置/详情封装
- users 管理封装
- `subscribe.library`

`/plugins/batch-delete` 当前只返回 501，且产品已明确不提供书源删除；应连同对应测试一并删除。其他后端路由需在完成调用者与权限审查后再决定，不因“前端没调用”直接删除。

## 3. 已确认的真实问题

### P0：Console API 权限边界不完整

`console_route()` 只负责注册路由。当前至少 21 个写接口没有调用 `require_admin()` 或 `require_user()`，包括插件启停、Ping/Smoke、设置保存、缓存清理、追更任务和 verification run。

前端 `AdminOnly` 只能隐藏页面，不能保护 API。必须先建立服务端默认拒绝策略，再做 UI 精修。

目标策略：

- `/api/console` 默认要求已登录管理员。
- 明确列出的阅读接口降级为普通用户可访问。
- Reading/Legado 外部契约继续使用其自身认证/网络边界，不并入 Console 权限。
- 增加匿名 401、普通用户 403、管理员成功的权限矩阵测试。

### P0：错误响应契约不一致

部分不存在资源返回 HTTP 200 + `{ "error": ... }`。React Query 会将其视为成功，搜索任务可能持续轮询。

目标策略：

- 不存在资源统一 404。
- 参数或状态冲突统一 400/409。
- 前端只依赖 HTTP 状态进入 error 分支。
- 为搜索任务不存在、候选不存在、插件不存在补回归测试。

### P1：文档和视觉基线失真

- 旧规划仍要求已删除的 MasonryGrid/旧卡片体系。
- 旧视觉报告仍宣称 99.17%，但当前代码与旧 `untitled/` 的差异包含主动删除项。
- `untitled/` 缺少登录、权限、章节详情、独立官方源等真实路由，不能继续作为完整验收基线。

### P1：必要交互状态覆盖不足

需要覆盖的不是更多装饰页面，而是真实状态：

- 登录失败、未登录跳转、普通用户访问管理员路由
- 移动导航展开
- 书库空态/错误态
- 搜索超时、失败、无结果
- 官方源空列表、登录中、失败、取消、成功
- 设置脏状态、保存中、失败、成功

### P1：基础交互质量

- 注销官方源、清除 Cookie 增加确认
- 修复设置 Label 关联、图标按钮名称、搜索输入名称
- 书库导航卡片改为真实链接语义
- 退出登录失败显示反馈

### P2：伪配置和过时文案

- `source_batch_size` 目前固定为 20 且不可保存；从设置响应和旧设计稿中移除，继续作为运行时内部常量。
- “规则引擎”“免限制登录”等营销式描述改为准确的插件运行与官方认证文案。

## 4. 执行顺序

### 阶段 A：同步真相与冻结范围 ✅

本轮完成：

- `PRODUCT.md` 继续作为产品范围与阶段真相。
- 旧重构/迁移文档标记为历史记录。
- 更新视觉进度，停止使用主动删除前的差异数字判断完成度。
- 本文档成为后续 Console 收尾入口。

验收：后续代理不会恢复 Cache/Verification/AI/旧卡片/无实现控件。

### 阶段 B：API 权限与错误契约 ✅

建议文件：

- `backend/app/api/console.py`
- `backend/app/services/user_auth.py`
- `dev-assets/tests/test_plugin_console_api.py`
- 搜索/书库 API 定向测试

步骤：

1. 建立 Console 默认管理员、阅读端点显式普通用户的路由策略。
2. 覆盖所有 Console 路由权限矩阵。
3. 将顶层 `{error}` 成功响应迁移为 4xx。
4. 验证前端错误态与轮询终止。

验收：匿名写接口全部 401，普通用户管理写接口全部 403；不存在任务不再轮询。

完成结果：Console 路由默认管理员访问，阅读接口显式开放普通用户；顶层不存在资源和参数错误改为标准 4xx，并补权限/404 回归测试。

### 阶段 C：删除死前端契约 ✅

建议文件：

- `frontend/src/lib/api.ts`
- `backend/app/api/console.py`（仅删除 501 batch-delete）
- 对应测试

步骤：

1. 删除无调用者前端 API 方法。
2. 删除 inert `/plugins/batch-delete`。
3. 保留有后台、脚本、外部协议或明确延期价值的后端路由。
4. 删除 `source_batch_size` 设置投影，不新增配置项。

验收：`rg` 无死封装；lint/build/test 通过；外部 Reading/Legado 契约不变。

完成结果：删除 30 个无生产调用者的前端 API 封装、永久 501 的 batch-delete 路由及伪 `source_batch_size` 设置投影。

### 阶段 D：必要 UI 收口 ✅

只处理真实交互缺口：

1. 破坏性操作确认与退出错误反馈。
2. 空态、错误态、loading 状态。
3. Label、aria-label、链接语义和焦点状态。
4. 准确文案。

不恢复导入、删除书源、候选 Trace 操作、AI 控件或空壳工具页。

完成结果：补官方源注销/Cookie 清理确认、全局退出失败反馈、查询重试与空态、登录能力重试、表单 Label/aria 语义，并统一结构化 API 错误消息。

### 阶段 E：重建视觉回归基线 ✅

1. 以当前真实路由和已批准功能面创建 baseline。
2. 覆盖 desktop/mobile、admin/user 和关键错误/空状态。
3. 为独立官方源、插件详情、章节详情、登录页补基线。
4. 新基线建立后，以 >=98% 作为后续回归阈值，不再要求匹配旧 `untitled/` 的已删除控件。

完成结果：建立 39 个真实路由/角色/状态场景的 desktop/mobile 基线；默认 compare 要求像素加权整体及每个场景一致率均不低于 98%。最新报告为 `frontend/visual-diff/output/2026-07-15_17-23-59-491/report.md`，一致率 100%。

### 阶段 F：回归产品路线（下一步）

完成 B-E 后进入 `PRODUCT.md` Phase 1：共享书实体与用户订阅关系解耦。其后再处理：

- 持久化搜索任务恢复
- 上一章/下一章、阅读位置和基础显示控制
- 统一数据完整性扫描与运营恢复入口

## 5. 统一验收

```powershell
cd C:\Home\Workspace\UGit\legado-hub
.\verify.ps1

cd frontend
npm run lint
npm run build
npx vitest run
node .\visual-diff\run-visual-diff.mjs
```

任何阶段不得以恢复无实现控件、增加空壳页面或新增依赖来降低视觉 diff。

本轮最终验证：`verify.ps1` 通过；后端 `247 passed, 5 skipped`，插件校验全部通过，前端 `11 passed`，依赖审计 0 vulnerabilities，运行时数据无变化。
