# Reading 调用与订阅就绪优化计划

> 状态：Complete
> 日期：2026-07-17
> 主程序仓库：`C:\Home\Workspace\UGit\legado-hub`
> 官方插件仓库：`C:\Home\Workspace\UGit\QDFCCKK`
> 上位产品真相：`docs/PRODUCT.md`
> 所有权契约：`docs/architecture/subscription-ownership-and-progress-control.zh-CN.md`

## 1. 目标

本阶段优化“发现 -> 订阅 -> 首章可读 -> Reading 持续阅读”的交付链，不把 Console 扩展成阅读器：

1. Reading/Legado 的详情、目录和章节调用保持纯读，不订阅、不入队、不注册 TOC、不改变发布状态。
2. 已发布书籍搜索和发现把分页下推到 SQLite，不再为一页结果加载全部共享书及逐本读取 metadata。
3. TOC 一次加载章节索引与数据库投影，不读取每章正文；单章调用只定位并读取一个 UTF-8 文件。
4. 订阅章节抽查与 Reading 使用同一共享文件和 `full/preview` 语义，不返回“处理中”伪正文。
5. 新建订阅、恢复订阅或第二位用户订阅已有未就绪共享书时，能够立即唤醒同一条共享处理链。
6. 订阅响应和详情返回明确的 provisioning 摘要及首个可读章节，不要求前端根据多个计数猜测。
7. 单个手工任务失败不终止整批或吞掉后续任务；初始处理采用有限次数重试，失败后仍保留周期恢复入口。

## 2. 固定边界

### 2.1 必须保持

- 同一本书只有一个 `aggregateBookId`、一份共享正文和一条共享任务。
- 普通用户只管理自己的 `status`、`startChapterIndex` 和 `autoArchiveOnComplete`。
- `updateIntervalMinutes`、并发、来源、超时、重试、积压上限和立即维护仍属于管理员或宿主。
- 已发布 Reading book/chapter ID 和 URL 保持稳定；免费全文、VIP 全文和付费预览的字段语义不变。
- `chapter_index.json` 与共享 Markdown 是读取边界；数据库字段只作为定位和摘要投影，不能让缺失文件被误报为可读。
- 测试隔离真实数据库、用户、Session、Cookie、配置和订阅数据。

### 2.2 本阶段明确不做

- 不新增 Web 阅读器、阅读位置同步、字体、分页或主题。
- 不引入 Redis、新队列、新数据库或前端状态库。
- 不在本阶段持久化订阅搜索任务；该工作需要独立 schema、迁移与重启恢复设计。
- 不修改 Qidian 官方插件协议或版本；若后续发现插件问题，只在 QDFCCKK 修改并同步。
- 不恢复 AI、Smoke 运行期检测或已主动清理的页面与控件。
- 不把旧 `subscription-throughput-optimization-plan` 中尚未验证的建议整体套入当前实现。

## 3. 能力契约

### 3.1 Reading 纯读契约

- Published search/explore 只查询 `search_visibility_status = 'visible'`，分页大小固定受限。
- Published detail/TOC/chapter 不命中时返回 404；不得回退到会入队或注册 TOC 的虚拟聚合路径。
- TOC 只暴露已有共享文件且拥有稳定 `readChapterId` 的章节。
- 单章读取拒绝路径逃逸、空正文、NUL 和 Unicode replacement character；预览返回 `contentAccess=preview`。
- 用户订阅章节读取允许 hidden 共享书的既有正文，但仍必须先校验该用户的订阅所有权。

### 3.2 Provisioning 摘要

统一对象字段：

```json
{
  "state": "ready|processing|error|paused",
  "readableChapterCount": 0,
  "previewChapterCount": 0,
  "pendingChapterCount": 0,
  "firstReadableChapter": {
    "chapterId": "encoded-id",
    "chapterIndex": 1,
    "title": "第一章",
    "contentAccess": "full|preview"
  }
}
```

- `ready` 只在至少存在一个可读取共享章节时成立。
- `processing` 表示共享任务可继续处理但尚无可读章节。
- `error` 表示共享任务错误且尚无可读章节；已有可读章节时仍为 `ready`，同时保留书级错误摘要。
- `paused` 只描述共享任务暂停且尚无可读章节，不映射个人订阅的暂停状态。
- `firstReadableChapter` 不存在时为 `null`，不得使用数字章节索引冒充可读取 ID。

### 3.3 唤醒规则

仅在用户订阅关系新建或从非 active 状态恢复时检查唤醒；重复 active 订阅保持幂等。管理员明确暂停或归档共享任务时不由普通用户唤醒；除此之外，满足任一条件则唤醒共享任务：

- 新建共享书；
- `searchVisibilityStatus != visible`；
- 共享任务为 `error`；
- `visibleProcessedChapters <= 0` 或 provisioning 尚无首个可读章节。

唤醒只作用于共享任务，不改变其他用户订阅设置。初始 source-map refresh 成功后在同一调度尝试继续 bootstrap；失败项有限重试，不能阻断同批其他书。

## 4. 实施阶段

### Phase A：读取热路径与纯读闭环

- 新增 published books 的数据库分页查询，并接入 Legado search/explore。
- 抽取一次性章节目录加载：index + DB projection + 安全文件定位。
- 章节列表先过滤和分页，再只读取当前页文件；TOC 不读取正文；chapter 只读目标文件一次。
- 用户订阅章节接口直接调用共享文件读取服务，不再经过 `Catalog -> AggregateProcessor` 的处理中占位路径。
- 补稳定 ID、preview/full、404、无写副作用和 I/O 次数回归。

阶段门禁：`test_subscribe_shared_reads.py` 及新增 Reading 定向测试集中通过。

### Phase B：订阅就绪与调度恢复

- 新订阅、已有未就绪书和归档恢复统一调用唤醒 helper。
- 初始订阅继续按 source-map refresh -> bootstrap 顺序执行，不引入额外 60 秒等待。
- `run_periodic_once` 对每个任务独立捕获异常；手工任务失败重新入队，后续任务继续执行。
- 初始后台 runner 使用有限次数、递增延迟重试；耗尽后由已提前设置的 `next_check_time` 进入周期恢复。
- 订阅创建和书籍详情返回 provisioning 摘要。

阶段门禁：`test_shared_book_scheduler.py`、`test_user_subscriptions.py`、订阅 API 定向测试集中通过。

### Phase C：前端状态同步

- 订阅成功后失效 `['library']`，再进入详情页。
- 管理员删除共享书成功后失效书库与该书详情缓存，再导航。
- 前端类型接入 provisioning 摘要；Console 只展示处理/首章可读状态，不增加阅读器能力。

阶段门禁：对应 Vitest、lint、build 集中通过。

### Phase D：最终验证与交付

- 更新本计划与 `PRODUCT.md` 状态和实际证据。
- 运行根目录 `verify.ps1`，比较受保护运行数据摘要。
- 不在未修改官方插件时更新 QDFCCKK 版本或执行无关同步。

## 5. 验收标准

1. Reading search/explore 每页只构造该页结果，debug 总数仍准确。
2. 一次 TOC 调用不读取章节 Markdown 正文；单章调用最多读取目标 Markdown 一次。
3. Reading 所有虚拟详情、TOC、章节缺失均为 404，数据库与文件状态不发生变化。
4. 用户可以读取自己订阅的 hidden 书已有正文，但不能读取未订阅书或其他用户资源。
5. 新订阅无需等待下一次 60 秒轮询即可开始 source-map refresh 和 bootstrap。
6. 已有 hidden/error/零可读共享书在新激活订阅后被唤醒；重复 active 订阅不重复启动处理。
7. 一个手工任务抛异常时，同批后续任务仍执行，失败任务进入有限重试。
8. 响应中 provisioning 与实际首个可读章节一致，不泄露源 URL、内部路径、Trace 或来源章节 ID。
9. 前端订阅与删除后不展示 30 秒旧书库缓存。
10. `verify.ps1` 通过且受保护运行数据未变化。

## 6. 测试节奏

- 不在每次小改后运行完整套件。
- Phase A、B、C 各自完成后运行一次对应集中测试。
- 仅在诊断失败时运行单个回归；它不替代阶段门禁。
- 最终交付前只运行一次完整 `verify.ps1`，并如实记录命令与结果。

## 7. 完成证据

截至 2026-07-17，本计划已完成：

- Published search/explore 使用 SQLite `COUNT + LIMIT/OFFSET`，不再为一页 Reading 结果逐本读取 metadata。
- 章节目录一次加载 `chapter_index.json` 与数据库投影；TOC 在正常数据上读取 0 个 Markdown，单章只读取目标 Markdown 一次，章节列表只读取请求页文件。
- `/api/legado` 继续只读取 visible 发布内容；用户订阅章节在 owner 校验后可读取 hidden 书已有正文，缺失正文明确返回 404，不返回处理中占位正文。
- 个人进度与 provisioning 由同一次目录扫描生成，返回 `ready/processing/error/paused`、全文/预览/待处理计数和稳定的首章可读 ID。
- 新订阅、已有未就绪书的新用户订阅和暂停后恢复会唤醒共享处理；重复 active 订阅保持幂等，管理员暂停/归档的共享任务不被普通用户覆盖。
- manual queue 单项异常不会中断同批任务；失败手工项重入队，初始 runner 最多 3 轮递增延迟重试，SQLite due time 保留周期恢复路径。
- `PluginScheduler` 构造与 `import app.main` 不再隐式删除 CookieStore 文件；验证前被旧构造期清理删除的空占位文件已按原结构恢复。
- 前端订阅和删除动作会同步失效书库/详情缓存，用户详情展示首章就绪状态。

阶段与最终验证：

- Phase A：`test_subscribe_shared_reads.py`，14 passed。
- Phase B：调度器、共享读取、用户订阅测试，39 passed。
- Phase C：2 个前端测试文件，10 passed；lint 与 build 通过。
- 最终 `verify.ps1`：后端 289 passed / 5 skipped；22 个插件 validator 全部通过；前端 46 passed；npm audit 0 漏洞；lint/build 通过；runtime import smoke 通过。
- 视觉报告：`frontend/visual-diff/output/2026-07-17_05-18-35-671/report.md`，39 场景，整体 99.86%，最低 98.09%，PASS。
- 最终保护检查：`Verification passed without runtime data changes.`

后续独立阶段仍包括：订阅搜索任务持久化与重启恢复、统一数据完整性扫描和管理员恢复入口。本阶段没有新增 schema，也没有修改或更新 QDFCCKK 官方插件版本。
