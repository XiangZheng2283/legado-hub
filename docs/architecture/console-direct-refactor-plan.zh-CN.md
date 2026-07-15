# `/console` 后台直接重构总规划（莫奈版）

> 状态：当前主规划
> 日期：2026-07-03

## 当前执行基准

当前阶段以 `untitled/` 为页面结构和交互基准。莫奈色系与 MediaStationGo 只作为视觉参考，不覆盖 `untitled/` 已明确给出的页面结构、字段和用户流程。

---

## 1. 核心决策

### 1.1 直接重构，而不是继续修补

从本阶段开始，LegadoHub 的 `/console` 视图层按“直接重构”推进：

- 不再把每个页面当作独立修补点。
- 不再以“先把这一页修顺眼”为目标。
- 不再新增第二套平行后台或 `/console-v2`。
- 保留现有路由、现有后端 API、现有权限判断与现有 React/Tailwind/shadcn 技术栈。
- 在现有路径上，直接替换整套后台外观、页面模板、卡片体系、布局规则与文案语气。

一句话定义：

> **这是对 `/console` 界面层的原地重构，不是增量美容。**

### 1.2 为什么改成直接重构

当前后台已经同时涉及：

- 导航与布局
- 用户入口页（订阅、书库）
- 详情页（书籍、章节）
- 工作台页（搜索、书源）
- 配置页（设置、官方源）
- 品牌语气与视觉体系

继续局部修补会带来 3 个问题：

1. 页面之间风格割裂，像多个产品拼在一起。
2. 每一轮都要处理“旧规则与新规则并存”的债务。
3. 越往后越难判断哪些代码是临时补丁，哪些是新基线。

因此从工程和产品两个角度，直接重构更省成本。

---

## 2. 目标状态

### 2.1 产品气质

新的 `/console` 不是传统运维后台，也不是视频站首页，而是：

- 一个更优雅的阅读订阅工具后台
- 一个兼具用户入口与管理能力的统一工作台
- 一个长时间使用也不会视觉疲劳的内容型后台

目标关键词：

- 优雅
- 克制
- 柔和
- 连续
- 轻快
- 有内容感，不傻傻堆砌

### 2.2 用户体验目标

后台需要同时满足两类用户：

- 普通用户：找书、订阅、看进度、进详情
- 管理用户：检查状态、维护书源、调试搜索、修复任务

统一体验原则：

- 普通用户先看到内容，不先看到后台操作。
- 管理能力存在，但不压住阅读与订阅主流程。
- 页面信息按层级展开，不做无意义卡片堆叠。
- 一个页面只回答一个主要问题。

---

## 3. 新视觉基线：白灰底 + 莫奈重点色

### 3.1 总方向

视觉色彩采用 **白灰底 + 莫奈重点色** 体系：

- 大面积背景和卡片使用白色 / 极浅灰
- 莫奈蓝/粉仅用于重点交互、状态、CTA，不做大面积背景
- 页面整体干净、现代、清爽

### 3.2 色彩角色

- `background`: `#f7f8fa` — 极浅灰背景，保持干净
- `card`: `#ffffff` — 白色卡片
- `foreground`: `#1f2933` — 深灰文字
- `muted-foreground`: `#6b7280` — 辅助文字
- `border`: `#e5e7eb` — 浅灰边框
- `secondary`: `#f3f4f6` — 次要容器 / muted

### 3.3 莫奈重点色

- `primary`: `#7e9fb3` — 莫奈灰蓝：主按钮、进度、选中态、当前页、主状态、节点
- `primary-foreground`: `#ffffff`
- `pink`: `#cfa2ad` — 莫奈灰粉：高关注 badge、危险动作、关键 CTA、管理提醒
- `pink-foreground`: `#ffffff`

### 3.4 语义分工

- 蓝：主按钮、进度、当前页、选中态、稳定提示
- 粉：结果数、高关注标签、关键 CTA、局部强调、危险动作
- 白灰：后台底色、卡片、容器、分隔、普通文案

### 3.5 视觉禁令

- 禁止莫奈色大面积铺背景
- 禁止米白/奶油色/泛黄背景
- 禁止高亮互联网蓝 + 荧光粉的强刺激搭配
- 禁止一堆大小相同的卡片上下平铺
- 禁止仅靠颜色区分层级，缺少留白、对齐和节奏

---

## 4. 全站信息架构与页面模板

### 4.0 UI 结构参考：MediaStationGo

从当前阶段开始，`/console` 的界面结构优先参考 `ShukeBta/MediaStationGo` 的前端实现。

参考仓库：

- `https://github.com/ShukeBta/MediaStationGo`

本项目只借鉴 UI 结构、页面组织和组件层级，不复制业务逻辑、API 调用或配色。

已确认的参考映射：

| LegadoHub 页面/模块 | MediaStationGo 参考 | 借鉴内容 |
|---|---|---|
| 订阅页结果 / 小说海报墙 | `web/src/pages/PosterWallPage.tsx` + `web/src/components/MediaCard.tsx` | 海报墙、内容墙密度、封面卡 hover、徽章覆盖层 |
| 书库页 | `web/src/pages/LibraryPage.tsx` + `LibraryMediaSections` | 影视库式内容浏览、库头部、内容区与详情区切换 |
| 书籍详情页 | `MediaDetailPage.tsx` / `LibrarySeriesDetailSection.tsx` | Hero、封面、元数据、操作区、详情分区 |
| 设置页 | `SettingsPage.tsx` + `SettingsRow.tsx` | 左/上分组、设置行、保存状态、分组式配置体验 |
| 后台管理页 | `AdminPage.tsx` / `AdminLibraryPanel.tsx` | 管理区分组、表格与面板组合 |
| 订阅管理 | `SubscriptionsPage.tsx` + `SubscriptionCard.tsx` | 订阅卡片、历史区、表单与列表分离 |

执行规则：

- 布局结构可以“直接抄” MediaStationGo 的成熟页面模式。
- 配色必须替换成 LegadoHub 的莫奈色系。
- 文案和数据字段必须替换成小说订阅语义。
- 不引入 MediaStationGo 的依赖栈；如果它用了 `framer-motion` 等本项目没有的依赖，用 Tailwind/CSS 做轻量替代。
- 不复制 MediaStationGo 的业务代码，只迁移 UI 结构和交互模式。

### 4.1 不变的路由边界

保留现有路由，不再创建平行 V2：

- `/console`
- `/console/subscription`
- `/console/admin/subscription`
- `/console/library`
- `/console/admin/library`
- `/console/library/:bookId`
- `/console/library/:bookId/chapters/:chapterId`
- `/console/search`
- `/console/plugins`
- `/console/plugins/:pluginId`
- `/console/official-sources`
- `/console/settings`

详情页继续共用：

- 不新增 `/console/admin/library/:bookId`
- 不新增 `/console/admin/library/:bookId/chapters/:chapterId`

### 4.2 后台页面模板

本次直接重构只允许使用 4 种页面模板：

#### 模板 A：内容入口页

适用：

- 订阅页
- 书库页

结构：

- 页面头部
- 搜索/筛选工具栏
- 瀑布流横板小卡片区
- 空状态 / 加载状态

#### 模板 B：详情页

适用：

- 书籍详情
- 章节详情
- 书源详情

结构：

- 返回
- Hero 信息区
- 主内容区
- 次级信息区 / 折叠维护区
- 日志 / 章节 / 状态标签页

#### 模板 C：工作台页

适用：

- 搜索工作台
- 书源页
- 官方源页

结构：

- 页面头部
- 紧凑工具栏
- 主表格 / 主结果区
- 辅助面板 / 折叠区 / 弹窗

#### 模板 D：配置页

适用：

- 设置页

结构：

- 页面头部
- 分组 section
- 保存操作区
- 状态反馈区

---

## 5. 卡片与布局体系

### 5.1 内容卡片跟随 MediaStationGo，不再强制横板

此前的“横板小卡片”不再作为硬性标准。

新的标准是：

- 小说订阅结果可以参考 MediaStationGo 的海报墙卡片。
- 书库可以参考 MediaStationGo 的影视库内容卡片。
- 卡片尺寸必须比传统大海报克制，但不要求横板。
- 封面可以成为内容墙视觉中心，但不能失控成巨型海报。

保留原则：

- 卡片要有内容浏览感。
- 卡片要能快速扫读。
- 状态、进度、最新章节、来源等信息不能被封面完全淹没。
- 管理操作后置到 hover、更多菜单或详情页。

### 5.2 小说海报墙

订阅页和书库页可以采用“小说海报墙”：

- 封面在上或作为主体
- 标题、作者、状态、最新章节作为下方/覆盖信息
- 可使用计数徽章、状态徽章、进度条覆盖层
- hover 时轻微上浮、封面轻缩放、操作层浮现

对应参考：

- MediaStationGo `PosterWallPage`
- MediaStationGo `MediaCard`

### 5.3 瀑布流保留

订阅页和书库页都保留 `MasonryGrid`：

- 用纯 CSS `columns`
- 不引入第三方瀑布流库
- 通过卡片高度差形成节奏感

瀑布流里可以承载：

- 海报墙卡片
- 横板信息卡片
- 管理增强卡片

具体形态由页面语义决定，优先参考 MediaStationGo。

### 5.4 卡片风格要求

- 克制
- 留白克制
- 层级清楚
- 一眼能扫到书名、作者、状态、最新章节、进度

卡片不应该：

- 过高
- 过厚
- 信息一坨
- 只靠大封面撑视觉

---

## 6. 直接重构的实施范围

### 6.1 第一批必须重构的页面

这批页面决定全站风格基线，优先级最高：

- `Layout.tsx`
- `Dashboard.tsx`
- `SubscriptionDiscoveryPage.tsx`
- `LibraryPage.tsx`
- `LibraryBookDetailPage.tsx`
- `LibraryChapterDetailPage.tsx`

### 6.2 第二批必须重构的页面

这批页面决定后台是否统一：

- `SearchJobs.tsx`
- `Plugins.tsx`
- `PluginDetail.tsx`
- `OfficialSourcesPage.tsx`
- `SettingsPage.tsx`

### 6.3 第三批收尾页面

- `LoginPage.tsx`
- `OfficialSourceLoginDialog.tsx`
- 若有仍残留旧视觉的 shared/ui 组件

---

## 7. 直接重构流程

本次不是“想到哪改到哪”，而是严格按阶段推进。

### 阶段 0：冻结旧规则，建立新基线

目标：

- 明确旧 bilibili 高亮蓝粉规范不再是视觉最终标准
- 把莫奈色系定为唯一新基线

输出：

- 本规划文档
- 新的视觉 token 定义
- 旧视觉规范降级为历史参考

完成判定：

- 团队后续实现不再争论“到底按 bilibili 还是按莫奈”

### 阶段 1：全局 token 与基础组件替换

目标：

- 替换 `index.css`
- 替换全局色彩语义
- 校正 `Badge`、`Button`、`Progress`、`Dialog`、`Tabs` 等基础组件

涉及文件：

- `frontend/src/index.css`
- `frontend/src/components/ui/*`

完成判定：

- 全站蓝粉高亮感消失
- 进入莫奈灰蓝/灰粉/米白体系
- 基础组件可复用

### 阶段 2：壳层与模板重构

目标：

- 先重做后台外壳，再重做内容页

涉及文件：

- `frontend/src/components/layout/Layout.tsx`
- `frontend/src/routes/Dashboard.tsx`

完成判定：

- 导航、页头、页面容器、快捷入口形成统一基调
- 后续页面可套统一模板

### 阶段 3：用户主流程重构

目标：

- 订阅页、书库页、书籍详情、章节详情形成完整的用户主流程

涉及文件：

- `SubscriptionDiscoveryPage.tsx`
- `LibraryPage.tsx`
- `LibraryBookDetailPage.tsx`
- `LibraryChapterDetailPage.tsx`
- `components/shared/*`

完成判定：

- 订阅 -> 入库 -> 进书籍详情 -> 进章节详情 形成完整闭环
- 全部为横板小卡片 + 瀑布流 + 柔和色系

### 阶段 4：管理工作台重构

目标：

- 搜索工作台、书源页、书源详情、官方源页统一成优雅后台

涉及文件：

- `SearchJobs.tsx`
- `Plugins.tsx`
- `PluginDetail.tsx`
- `OfficialSourcesPage.tsx`

完成判定：

- 不再像散乱调试页
- 仍然高密度，但结构清楚、气质统一

### 阶段 5：配置与边缘页重构

目标：

- 设置、登录、登录弹窗等边缘页面完成收口

涉及文件：

- `SettingsPage.tsx`
- `LoginPage.tsx`
- `OfficialSourceLoginDialog.tsx`

完成判定：

- 全站没有明显旧后台残留

### 阶段 6：清理与验收

目标：

- 删除旧实现
- 清理死代码
- 收敛 lint / build / 组件一致性

完成判定：

- 构建通过
- 定向 lint 通过
- 关键页面无明显视觉割裂

---

## 8. 长时间任务推进机制

为了保证这个后台可以长时间持续推进，而不是做两天就散架，执行时必须遵守下面的长期机制。

### 8.1 单一主规划

后续所有实现都以本规划为总入口：

- 新需求先挂到本规划阶段里
- 不再新增多个并行“重设计文档”互相打架

### 8.2 每阶段独立可交付

每一阶段结束都必须满足：

- 页面可运行
- `npm run build` 通过
- 本阶段改动文件定向 lint 通过
- 至少有一段简短书面总结

这样即使任务长时间推进，中途停下也不会烂尾。

### 8.3 只允许一个主视觉方向

从现在开始只允许一个视觉方向存在：

- 莫奈色系
- 优雅的内容型后台
- MediaStationGo 式内容墙/影视库结构
- 瀑布流内容页

禁止来回摇摆：

- 不能一会儿 bilibili 高亮，一会儿莫奈柔和
- 不能一会儿 MediaStationGo 内容墙，一会儿普通后台网格
- 不能一会儿用户入口轻快，一会儿全站改回纯工具文案

### 8.4 先壳后页，先模板后特例

所有长期推进都遵守顺序：

1. 先全局 token
2. 先外壳布局
3. 再页面模板
4. 再具体页面
5. 最后修特例

这样不会每次都在页面里硬补。

### 8.5 每轮只扩一个层级

长任务执行规则：

- 一轮只做一个阶段或一个页面簇
- 不在同一轮里同时重写视觉、重写交互、重写数据流
- 避免把任务拖成不可收敛的大泥球

---

## 9. 完成判定

只有满足下面全部条件，整个后台直接重构才算完成：

### 9.1 视觉完成

- 全站统一进入莫奈色系
- 不再残留旧 bilibili 高亮蓝粉主视觉
- 页面不再像“后台卡片堆砌”

### 9.2 结构完成

- `/console` 各主要页面共享统一模板语言
- 用户入口与管理页层级清晰
- 页面不再各说各话

### 9.3 组件完成

- 内容墙卡片稳定
- 瀑布流稳定
- 基础组件语义统一

### 9.4 工程完成

- `npm run build` 通过
- 定向 lint 通过
- 旧死代码删除
- 不新增平行 V2 路由

### 9.5 产品完成

- 普通用户能顺畅完成：找书 -> 订阅 -> 看进度 -> 进详情
- 管理用户能顺畅完成：搜索 -> 检查 -> 管理书源 -> 调整设置

---

## 10. 与旧文档关系

### 当前有效关系

- 本文档：**主规划**
- `frontend-redesign-ui-design.md`：继续保留，作为页面边界与路由参考
- `bilibili-Design-System/legado-hub-ui-spec.md`：降级为历史实现参考，只保留密度、组件和语气层面的借鉴

### 明确废止

以下旧方向不再作为最终标准：

- 高亮 bilibili 蓝粉主视觉
- 无结构来源的自造卡片体系
- “只修几页”的补丁式推进

---

## 11. 下一步执行建议

直接进入下一轮时，执行顺序固定为：

1. 先提取 MediaStationGo 页面结构参考清单
2. 再写莫奈 token 与视觉替换清单
3. 再改 `index.css` 与基础 UI 组件
4. 再改 `Layout.tsx` + `Dashboard.tsx`
5. 再按 MediaStationGo 的海报墙/影视库/设置页结构重做订阅、书库、详情、设置
6. 再改搜索/书源等后台工作台页面
7. 最后做清理与验收

这份规划的目的不是“描述一个想法”，而是：

> **保证 `/console` 后台能在长时间任务中持续推进，并最终完成一轮真正的原地重构。**
