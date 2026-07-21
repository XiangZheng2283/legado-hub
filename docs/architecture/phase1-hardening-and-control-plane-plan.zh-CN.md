# Phase 1 加固与控制面补全计划

> 状态：Complete
> 执行进度：Phase A-E 已完成
> 日期：2026-07-16
> 主程序仓库：`C:\Home\Workspace\UGit\legado-hub`
> 官方插件仓库：`C:\Home\Workspace\UGit\QDFCCKK`
> 上位产品真相：`docs/PRODUCT.md`
> 领域契约：`docs/architecture/subscription-ownership-and-progress-control.zh-CN.md`

## 1. 目标

把当前“核心订阅和 Reading 闭环可用”的状态收口为可交付的受控多用户版本：

- 普通用户能够搜索、订阅和管理自己的书籍，但不能控制共享抓取资源。
- 管理员能够在 Console 管理用户、全局配额和单书处理节奏。
- Reading/Legado 继续作为阅读主界面，Console 只提供订阅、进度观察和运维抽查。
- 起点官方插件只从 QDFCCKK 修改并同步，宿主 CookieStore 是插件运行时登录态的唯一真相。
- 发布门禁覆盖后端、前端、插件、视觉回归和可选真实官方源验收。

本计划完成后，`docs/PRODUCT.md` 的 Phase 1 才能从 `Active` 改为 `Complete`。

## 2. 固定边界

### 2.1 必须保持

1. Reading/Legado 负责阅读位置、翻页、字体、主题和阅读体验。
2. 普通用户只能调整 `status`、`startChapterIndex` 和 `autoArchiveOnComplete`。
3. 管理员才可调整全局配额、`updateIntervalMinutes` 和 `backlogChapterLimit`。
4. Reading 数据面可读取 `visible` 已发布共享内容和启用的第三方插件结果；官方、禁用、未知或跨声明域名的插件 ID 不开放。读取不得隐式订阅、创建聚合任务、入队或维护。
5. APP 章节正文链固定为普通 App 正文、VIP 正文、付费预览，不回退 Web。
6. 插件运行时不得读取或写入插件目录、用户目录或其他进程外 Cookie 文件。
7. 当前真实用户、Session、宿主 Cookie 和配置必须保留。

### 2.2 明确不做

- 不新增 Web 阅读器、阅读位置同步或排版设置。
- 不向普通用户开放并发、来源、重试、优先级和立即处理。
- 不恢复已删除的 Cache、Verification、AI 校对或旧设计稿空壳页面。
- 不引入 Redis、新队列、第二数据库或新的前端状态库。
- 不把真实外网调用变成普通开发验证的强制步骤。

## 3. 实施原则

- 复用现有 `CookieJar`、`AppConfig`、SQLite、React Query 和 UI 组件。
- 先修根因和共享边界，不在每个调用者增加重复补丁。
- 数据库变更只做可重复、向前兼容的原地迁移，不删除 `app.db`。
- 新增输入只接受白名单字段，所有权限在服务端执行。
- 真实凭据不进入仓库、测试夹具、日志、Trace 或截图。
- 小任务完成全部修改后统一测试；大任务按下列 Phase 集中验证；最终提交前再运行完整门禁。

### 3.1 已完成前置门禁

本计划建立在已完成的 v8 -> v9 原地迁移修复之上：数据库版本按整数比较，不再因旧版本删除 `app.db`；`test_db.py` 已覆盖重复初始化以及升级后保留用户和 Session。Phase B/C 的每个数据库阶段都必须继续运行该测试，迁移安全回归失败时停止后续工作。

## 4. Phase A：官方插件凭据与正文边界

### 范围

权威修改位于 QDFCCKK，完成后同步 APP/WEB 到 legado-hub。

### 任务

1. `AppApiClient(ctx)` 有宿主上下文时只从 `ctx.cookies` 加载登录态。
2. 有宿主上下文时，token 刷新通过 `ctx.cookies.merge()` 持久化；只有显式传入 `cookie_path` 的独立脚本允许文件持久化。
3. VIP/Fock 解密结果应用与普通正文相同的乱码拒绝规则。
4. WEB 短信登录 fallback 只接受明确用户名或合法中国大陆手机号。
5. Cookie 粘贴身份字段中的手机号必须是合法明文或合法掩码；普通用户名仍允许非空字符串。
6. 为 APP/WEB 增加最小离线回归：宿主 CookieStore、非法手机号、VIP 乱码、无 Web 正文回退。
7. 同步脚本生成不含时间戳的来源记录，至少包含 QDFCCKK commit、variant 和 plugin id。
8. 修正 QDFCCKK 根 README、APP/WEB README 和 AGENTS 中已经漂移的目录、Cookie 与宿主能力说明。

### 验收

- 宿主模式不会访问 `~/.qidian_app_lib/Cookie.json`。
- token 刷新后下一次插件实例可从宿主 CookieStore 读取。
- 免费全文、VIP 全文和付费预览分类不变；乱码不作为正文返回。
- APP/WEB 登录均只有明确用户名或合法登录手机号才成功。
- APP/WEB 离线 smoke 和 legado-hub 插件 validator 通过。

## 5. Phase B：管理员控制面补全（已完成）

### 任务

1. 新增管理员用户管理页：列表、创建、禁用/启用、重置密码。
2. 用户管理页面不展示密码；创建和重置使用一次性输入，成功后立即清空。
3. Settings 增加订阅政策编辑：
   - `maxActivePerUser`
   - `maxNewSharedBooksPerDay`
   - `maxGlobalProvisioningBooks`
4. 管理员书籍详情增加单书处理设置：
   - `updateIntervalMinutes`，范围 `10..1440`
   - `backlogChapterLimit`，范围 `5..100`
5. 前端复用现有 API 错误结构和 Dialog/Input/Switch/Button，不新增表单依赖。
6. 后端拒绝用户、配额和单书设置中的未知字段。

### 验收

- 管理员可以完全通过 Console 建立和维护普通用户。
- 普通用户看不到页面且直接调用接口仍为 403。
- 配额和单书设置保存后刷新页面仍保持，并立即影响后续检查。
- 个人设置不会改写共享任务设置。

### 完成证据（2026-07-16）

- Console 已接通用户列表、创建、启用/禁用和密码重置；服务端阻止自禁用和最后一个可用管理员失效。
- `/api/console/settings` 已暴露并严格校验三个订阅配额，单进程并发更新不会互相覆盖。
- 管理员书籍详情已接通单书处理间隔与积压上限；更新间隔后同步重排 `next_check_time`。
- 普通用户路由和服务端 API 均无法访问管理员控制面，个人订阅设置仍保持独立。
- 后端默认测试：`268 passed, 5 skipped`；前端：`23 passed`；`npm run lint`、`npm run build` 通过。

## 6. Phase C：并发、限流、审计与敏感信息（已完成）

### 任务

1. 在 `UserSubscriptionsService.ensure()` 的同一 `BEGIN IMMEDIATE` 事务中重新检查活跃订阅配额并 upsert，消除并发超额窗口。
2. 复用现有共享书身份锁；只为“新建共享书配额检查到创建”增加最小单进程互斥，不新增持久化预留系统。
3. 为受控订阅入口增加按用户的内存滑动窗口限流：搜索、订阅创建、订阅更新分开计数；默认值进入 `SubscriptionConfig`，管理员可调。
4. 限流返回结构化 HTTP 429；进程重启清空计数是当前受信局域网单进程部署的接受上限。
5. 新增通用持久化审计表和最小服务，记录：
   - 用户创建、禁用/启用、重置密码
   - 官方源登录成功/失败、注销、Cookie 清理
   - 订阅创建与个人设置变化
   - 管理员共享书维护
6. 审计只记录摘要，不记录密码、验证码、Cookie、Authorization、完整手机号或正文。
7. `LoginTraceStore` 在写入前递归脱敏敏感键，并限制错误字符串长度。

### 验收

- 并发不同书订阅不能突破用户上限。
- 超出速率返回 429，其他用户不受影响。
- Trace 与审计中不存在验证码、Cookie、token、密码和完整手机号。
- 禁用用户立即失效全部 Session。

### 完成证据（2026-07-16）

- `ensure()` 与归档恢复在同一 `BEGIN IMMEDIATE` 事务中复查容量并写入，单用户并发不同书不会突破活跃上限。
- 新共享书容量检查、创建和订阅关系由跨 event loop 的单进程锁保护；现有按书处理锁保持不变。
- 搜索、订阅创建和个人设置更新按用户独立滑动窗口限流，管理员可调整四个频率参数，429 返回重试秒数。
- schema 10 原地新增 `audit_events`；迁移失败整事务回滚，用户、Session 和既有表不删除。
- 用户管理、官方源登录/注销/Cookie 清理、订阅和管理员共享书维护写入白名单摘要审计。
- Login Trace 对嵌套敏感键和普通字符串递归脱敏，并限制深度、条目数、错误和字符串长度。
- 后端默认测试：`276 passed, 5 skipped`；前端：`23 passed`；`npm run lint`、`npm run build` 通过。

## 7. Phase D：前端错误恢复与状态语义（已完成）

### 任务

1. 为订阅发现、书库、详情、Dashboard、插件详情和设置错误态增加真实 `refetch()` 重试。
2. 统一 401/403/404/429/503 的用户文案，保留后端结构化错误消息。
3. 官方源浏览器登录轮询增加截止时间，超时后停止轮询并允许重新发起。
4. 用户动作使用显式 action/status 映射，未知动作不默认归档。
5. 补关键交互测试：用户管理、配额、单书设置、错误重试、登录轮询超时。

### 验收

- 错误页面不需要整页刷新即可恢复。
- 403 不伪装成 404 或通用网络错误。
- 登录流程不会无限轮询。
- visual diff 不通过恢复假数据或空壳控件达标。

### 完成证据（2026-07-16）

- 新增统一 `apiErrorMessage()`：后端 `detail.message` 优先；无后端文案时明确区分 401、403、404、429 和 503。
- 订阅发现、书库、书籍详情、Dashboard、插件详情和设置页的查询错误均可直接调用对应 React Query `refetch()` 恢复。
- 普通用户书库、管理员书库和单书维护动作改为显式映射；未知动作直接拒绝，不再默认归档或重建。
- 官方源浏览器登录轮询增加 5 分钟硬截止；即使状态请求悬挂也会解除轮询，允许重新发起，卸载时清理全部计时器。
- 前端测试：`42 passed`；`npm run lint`、`npm run build` 通过，仅保留既有 Vite 单包体积警告。

## 8. Phase E：发布门禁、文档与技术债（已完成）

### 任务

1. `verify.ps1` 纳入默认视觉 compare，执行 `frontend/visual-diff/run-visual-diff.mjs`，并以整体及单场景均不低于 98% 为失败门槛。
2. 发布验证依次执行：QDFCCKK 离线 smoke、同步、宿主 validator、后端测试、前端 test/lint/build、视觉 compare、运行数据快照。
3. 增加重复 PATCH、全订阅 API owner 隔离、敏感字段扫描和配额并发测试。
4. 更新 `PRODUCT.md`、订阅契约、视觉进度和 QDFCCKK 文档的最终状态。
5. 扫描旧共享字段调用者；本轮只停止活动语义。物理删列仅在无调用者且单独迁移测试齐备时执行。
6. 持久化搜索恢复、统一完整性扫描和公网部署安全继续作为 Phase 1 后续能力，不阻塞本地/受信局域网交付。

### 完成证据（2026-07-16）

- `verify.ps1` 已接入默认 visual compare；脚本要求整体及每个场景均不低于 98%，且视觉服务端口占用时自动选择空闲端口。
- 重复订阅更新无变化时不再重复写状态、operation log 或 audit；更新限流只对实际变化计数。
- 新增订阅端点 owner 隔离、递归私有字段扫描和 API 并发配额回归；用户正文 DTO 移除内部 `debug`。
- QDFCCKK WEB/APP 离线回归、同步、宿主 validator 和逐文件哈希比对通过；APP 真实 API 验证免费全文 2348 字、VIP 预览 182 字。
- 根验证通过：后端 `281 passed, 5 skipped`，22 个插件 validator 通过，前端 `42 passed`，依赖审计 0 漏洞，lint/build 通过。
- 最新视觉报告 `frontend/visual-diff/output/2026-07-16_11-42-07-610/report.md`：39 场景、整体 99.85%、最低 98.25%、结果 PASS。
- 同步与最终验证前后受保护运行摘要完全一致；真实用户、Session、Cookie、配置和运行数据未变化。
- `added_by_user_id` 仍有内部查询和管理员投影调用者，本阶段仅停止其订阅读写真相，未物理删列。

### 最终验收

```powershell
cd C:\Home\Workspace\UGit\QDFCCKK
.venv\Scripts\python source-plugin\WEB-plugin\smoke\validate_offline_regressions.py
.venv\Scripts\python source-plugin\APP-plugin\smoke\validate_offline_regressions.py
python sync-to-legado-hub.py --variant WEB-plugin
python sync-to-legado-hub.py --variant APP-plugin

cd C:\Home\Workspace\UGit\legado-hub
.\verify.ps1
```

真实 Qidian 验证在日常阶段测试中只在凭据存在时运行；在 Phase 1 标记 `Complete`、发布或更新官方插件版本前必须运行。凭据从宿主 CookieStore 或环境变量读取，不写入报告：

```powershell
cd C:\Home\Workspace\UGit\QDFCCKK
.venv\Scripts\python source-plugin\APP-plugin\smoke\validate_app_api.py
```

最终发布门禁在同步前记录 `backend/data`、`backend/config`、用户和 Session 摘要，完成 QDFCCKK 离线/真实验证、同步和 legado-hub 验证后再次比较。允许变化的只有 `plugins/sources/official/qidian_com_*` 同步产物和 visual-diff 输出；真实运行数据、宿主 Cookie、配置、用户和 Session 不得变化。

## 9. 依赖顺序

```text
已完成前置：v8 -> v9 安全迁移
    -> Phase A 官方插件边界
    -> Phase B 管理员控制面
    -> Phase C 并发/限流/审计
    -> Phase D 前端错误恢复
    -> Phase E 最终发布门禁
```

Phase B 的纯前端页面可以与 Phase A 并行探索，但主线程按上述顺序整合，避免跨仓库同步和 shared contract 同时变化。

## 10. 完成定义

只有以下条件同时满足，Goal 才能结束：

- 本计划 Phase A-E 验收全部通过。
- 当前真实用户、Session、Cookie、配置和运行数据未被测试修改。
- 两个仓库差异经过安全字段审查。
- QDFCCKK 是官方插件唯一修改源，legado-hub 同步副本哈希一致。
- `docs/PRODUCT.md` 与实际完成状态一致。
- 未恢复 Web 阅读器、用户级抓取控制、AI 或旧设计稿空壳能力。
