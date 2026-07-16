# `/console` 后台直接重构进度

## 当前状态

- 前端迁移批次（原“阶段 10”）：已完成
- 产品 Phase 0.5：已完成
- Console 收尾阶段 B-E：已完成
- 下一产品阶段：Phase 1 Subscription Ownership
- 后续 Console 收尾入口：`docs/architecture/console-capability-audit-and-next-plan.zh-CN.md`

## 完成范围

- 订阅 -> 入库 -> 详情 -> 章节正文阅读闭环（readChapterId 契约修复完成）
- 设置页优先级编辑闭环（textarea 编辑 primarySourcePriority / candidateSourcePriority）
- 管理页结构和视觉收口（Layout/Dashboard/SearchJobs/Plugins/PluginDetail/OfficialSources）
- LogStream 浅色化
- 未使用迁移残留清理
- readChapterId 契约：db_row chapter_id 优先，否则 VIRTUAL_SOURCE_ID + make_aggregate_chapter_url + encode_chapter_id。不 fallback 到 sourceChapterId 或数字 chapterIndex。
- 测试验证：readChapterId 以 legadohub_ai_aggregate: 开头，非纯数字

## 本轮改动文件

- `backend/app/api/console.py` — readChapterId 契约修复 + 新增 imports
- `backend/app/services/library_books.py` — list_shared_chapters 补 readChapterId
- `frontend/src/lib/api.ts` — normalize 去掉 readChapterId fallback 链
- `frontend/src/routes/LibraryBookDetailPage.tsx` — chapterBodyQuery 仅 readChapterId 存在时启用
- `frontend/src/routes/SettingsPage.tsx` — 优先级 textarea 编辑
- `frontend/src/components/layout/Layout.tsx` — 设计稿导航分组
- `frontend/src/routes/Dashboard.tsx` — 设计稿 admin/user 双模式
- `frontend/src/routes/SearchJobs.tsx` — 设计稿结构
- `frontend/src/routes/Plugins.tsx` — 设计稿结构
- `frontend/src/routes/OfficialSourcesPage.tsx` — 设计稿结构
- `frontend/src/components/shared/LogStream.tsx` — 浅色化
- `dev-assets/tests/test_subscribe_shared_reads.py` — readChapterId 断言
- `docs/architecture/console-direct-refactor-plan.zh-CN.md` — 执行基准更新
- `docs/architecture/console-direct-refactor-progress.zh-CN.md` — 状态更新
- 删除: CachePage.tsx, VerificationPage.tsx, BookCard.tsx, SubscriptionCard.tsx, MasonryGrid.tsx

## 验证结果

- `npm run build` ✅ 通过
- `npm run lint` ✅ 0/0
- 后端 `import app.main` ✅
- `test_subscribe_shared_reads.py` ✅ 3 passed
- readChapterId 断言 ✅ `legadohub_ai_aggregate:` 前缀，非纯数字

## Phase 0.5 关键工作流修复（2026-07-12）

- 移动端使用统一导航菜单，管理员可直达 `/console/official-sources`；普通用户不会看到管理员入口。
- 官方源认证接口统一由后端 `require_admin` 保护；浏览器登录只有通过明确账号名或手机号身份探测才算成功。
- 搜索、订阅、书库维护、章节正文和官方登录失败均显示就地错误；超时或过期任务不再无限轮询。
- 设置分区按顺序保存，失败时保留未保存状态；章节列表支持分页并统一可读性判断。
- 移除删除书源、导入规则、Trace 等无实现控件；禁用/筛选/触屏操作保持可用。
- AI 校对不属于当前产品功能面，章节详情仅保留来源、对齐和处理状态信息。
- 这里的 Trace 指无实现的操作控件；章节详情中的只读 Trace 摘要作为运营证据保留。
- Cache/Verification 页面及旧 Aggregate 页面体系属于主动清理，不作为待恢复功能。

Console 收尾阶段 B-E 已完成。下一步进入 Phase 1；Phase 1 在 schema 变更前补充共享书可见性与权限决策。
