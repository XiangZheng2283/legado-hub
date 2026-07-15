# 基于新设计稿重做前端 — 实施规划

> 以 `untitled/` 为唯一设计来源，在 `frontend/` 内直接重建，不依赖旧页面结构。

## 1. 策略

- `untitled/src/pages/` 是页面结构和交互的唯一参考
- `frontend/` 保留我们的基础设施（路由、API、auth、构建配置），其余全部按设计稿重建
- 不使用旧页面的逐行适配方式；每个页面从设计稿的组件层级出发重新组织

## 2. 保留 vs 替换

| 保留 | 替换 |
|---|---|
| `package.json`、`vite.config.ts`、`tsconfig.json` | 全部 `routes/*.tsx` |
| `src/lib/api.ts`、`src/lib/auth.tsx` | `src/components/shared/*`（自写组件不再需要） |
| `src/components/ui/*`（shadcn，继续用同名组件承载设计稿样式） | 旧 `BookCard`、`SubscriptionCard`、`MasonryGrid` |
| `src/App.tsx` 路由结构（`/console/*`） | `src/index.css` 改为设计稿色系 |
| `src/components/layout/Layout.tsx`（结构不换，跟设计稿侧栏对齐） | |

## 3. 步骤

### 步骤 1：更新 CSS token
`index.css` 改为设计稿色系（`slate-*` + `blue-*`）。已完成。

### 步骤 2：重建 Layout
对照设计稿 `DashboardLayout.tsx` 更新我们的 `Layout.tsx`：
- 导航分组（"发现 & 阅读" / "管理员工具"）
- 激活态 `bg-slate-100 text-slate-900`
- 左下角角色标识
- 底色 `bg-slate-50`

### 步骤 3：重建 Dashboard
对照设计稿 `Dashboard.tsx` 重写：
- admin 模式：KPI 卡片 + 快速入口 + 活动日志
- user 模式：居中 welcome + 两张快捷卡片 + 最近更新网格
- 使用我们已有的 `api.status()` 数据

### 步骤 4：重建订阅页
对照设计稿 `Subscriptions.tsx` 重写 `SubscriptionDiscoveryPage.tsx`：
- 居中搜索页 + 圆角搜索框
- 搜索中 indeterminate 进度条
- 横版结果卡片（封面+标题/作者/字数/章节+摘要+状态徽章）
- 已入库卡片直接跳转、未入库卡片弹出简洁订阅弹窗
- admin 事件日志折叠区
- 接入我们已有的 `api.subscribe.*` 调用

### 步骤 5：重建书库页
对照设计稿 `Library.tsx` 重写 `LibraryPage.tsx`：
- 圆角搜索框 + 筛选按钮
- 卡片网格（sm:2 lg:3 xl:4 列）
- 横版卡片：封面 + 书名/作者 + 状态 + 最新章节 + 摘要 + 进度条 + 可阅读计数
- admin 三点菜单：重新处理/暂停继续/归档/删除
- 接入我们已有的 `api.libraryBooks()` 调用

### 步骤 6：重建书籍详情页
对照设计稿 `BookDetail.tsx` 重写 `LibraryBookDetailPage.tsx`：
- Hero：封面左 + 书名/作者 + chip badges + 订阅状态 + 免费/VIP 分界 + 简介 + 进度
- 管理下拉菜单（检查更新 + MoreVertical 下拉）
- 元数据 Key-Value 卡片
- 源映射摘要卡片（健康状态 + 主源 + 候选源表格）
- 章节列表：搜索+筛选 + 500px 滚动容器 + sticky header + 状态区分点击
- 实时日志（复用 LogStream）
- 阅读弹窗（预览模式区分）
- 接入我们已有的全部 API 调用

### 步骤 7：重建设置页
对照设计稿 `Settings.tsx` 重写 `SettingsPage.tsx`：
- 6 个 Tab（通用/安全/书源池/聚合策略/优先级/词库）
- SettingRow 组件模式（左 label+desc / 右 input）
- sticky 保存栏
- 接入我们已有的 `api.settings` / `api.aggregateSettings` / `api.lexiconStatus` 调用

### 步骤 8：适配搜索工作台
对照设计稿 `SearchWorkbench.tsx` 重写 `SearchJobs.tsx`：
- 搜索框 + 统计面板
- 聚合结果表格 + 源执行流水侧栏
- 接入我们已有的 `api.createSearchJob` / `api.searchJob` 调用

### 步骤 9：适配书源页
对照设计稿 `Sources.tsx` 重写 `Plugins.tsx`：
- 标题 + 操作按钮
- 批量操作栏
- 表格（checkbox + 名称/ID/类型/能力/状态/Smoke/操作）
- 接入我们已有的 `api.plugins` 调用

### 步骤 10：适配官方源页
对照设计稿 `OfficialSources.tsx` 重写 `OfficialSourcesPage.tsx`：
- 统计卡片（暗色 + 正常）
- 官方源表格
- 接入我们已有的 `api.officialSources` 调用

### 步骤 11：清理
- 删除不再使用的共享组件（`BookCard`、`SubscriptionCard`、`MasonryGrid`）
- 确认 `LogStream` 适配新色系

### 步骤 12：验证
- `npm run build`
- `npm run lint`
