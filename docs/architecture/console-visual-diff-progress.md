# `/console` 后台视觉对齐进度

## 最新 visual diff 报告

`frontend/visual-diff/output/2026-07-09_08-54-00-015/report.md`

## 当前结论

- 整体平均 mismatch：约 **0.83%**
- 整体设计稿相似度：约 **99.17%**
- 目标：整体相似度至少 98%（平均 mismatch <= 2%）已达成
- 当前最高单项：`mobile-sources` 4.23%，其余视图均低于 1.39%

## 本轮关键改动

### 1. 全局字体基线回归设计稿

- `frontend/src/index.css`
- 移除 `body` 上的 `HarmonyOS_Medium` 自定义字体覆盖，回到 Tailwind/system 默认字体栈。
- 该项显著消除多页面文字抗锯齿差异。

### 2. 共享组件对齐

- `frontend/src/components/ui/button.tsx`
  - 移除 `whitespace-nowrap`，恢复设计稿按钮换行/收缩行为。
- `frontend/src/components/ui/table.tsx`
  - 表格边框、表头/单元格间距对齐设计稿：`border-slate-200`、`px-4`、`p-4`。
- `frontend/src/components/ui/tabs.tsx`
  - Tabs 根节点补 `flex flex-col gap-4`。
  - TabsContent 移除额外 `mt-2`，修复 Settings 内容整体上移。

### 3. 搜索工作台回归设计稿结构

- `frontend/src/routes/SearchJobs.tsx`
- 搜索按钮恢复「发起调试搜索」宽按钮。
- 统计数字恢复 `text-2xl`。
- 聚合结果矩阵取消移动端固定窄列宽，回到设计稿表格密度。

### 4. 书源管理页继续压差异

- `frontend/src/routes/Plugins.tsx`
- 筛选卡片增加 `!mt-8`，让筛选区、批量栏、表格整体下移到设计稿位置。
- 表格列名、作者信息、格式/分类、解析能力、健康指标、启用开关、操作按钮对齐设计稿。
- mobile 筛选标签使用窄宽度换行，贴近设计稿手机布局。
- `frontend/visual-diff/run-visual-diff.mjs`
  - 插件 mock 调整为设计稿同批数据与顺序：起点、笔趣阁、拷贝漫画、Wenku8、塔读、未知小站。
  - 补 `successRate`，保持 KPI 为 6 总数 / 5 启用 / 3 登录态 / 75.0% 连通度。

### 5. 书籍详情页细节修正

- `frontend/src/routes/LibraryBookDetailPage.tsx`
- `wordCount` 已带 `字` 时不再重复追加，修复移动端 badge 换行导致的 hero 区错位。

## 最新结果

| Viewport | Page | Mismatch |
| --- | --- | ---: |
| desktop | 仪表盘 | 0.29% |
| desktop | 订阅搜索结果 | 0.46% |
| desktop | 书库 | 0.54% |
| desktop | 书籍详情 | 0.77% |
| desktop | 搜索工作台 | 1.30% |
| desktop | 书源管理 | 1.39% |
| desktop | 系统设置 | 0.12% |
| mobile | 仪表盘 | 0.00% |
| mobile | 订阅搜索结果 | 0.85% |
| mobile | 书库 | 0.52% |
| mobile | 书籍详情 | 0.14% |
| mobile | 搜索工作台 | 1.07% |
| mobile | 书源管理 | 4.23% |
| mobile | 系统设置 | 0.00% |

## 验证命令

```powershell
cd C:\Home\Workspace\UGit\legado-hub\frontend
node .\visual-diff\run-visual-diff.mjs
npm run lint
npm run build
```

## 后续可选优化

- `mobile-sources` 仍是最高单项，可继续细调移动端 tabs / filter / bulk bar 的像素级间距。
- 当前整体目标已达成，后续优化属于单页精修。
