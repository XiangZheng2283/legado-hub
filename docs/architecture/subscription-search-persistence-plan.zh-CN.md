# 订阅搜索持久化与重启恢复计划

> 状态：Complete
> 日期：2026-07-17
> 上位产品真相：`docs/PRODUCT.md`
> 所有权契约：`docs/architecture/subscription-ownership-and-progress-control.zh-CN.md`

## 1. 目标

1. 订阅搜索任务、公开卡片和候选组在进程重启后仍可按原 `jobId` 查询。
2. owner 校验保持服务端强制；其他用户继续得到 404。
3. 已完成搜索重启后仍可使用原候选卡订阅。
4. `pending/running` 在启动时收口为 `interrupted`，前端停止轮询并允许重新搜索。
5. 搜索持久化不修改共享书、订阅关系、Cookie、插件或 Reading 数据面。

## 2. 最小数据模型

schema 11 新增一张表：

```text
subscription_search_jobs
  job_id              PK
  owner_user_id       FK users(user_id) ON DELETE CASCADE
  keyword
  page
  status
  payload_json        counters + cards + cardGroups + last 50 events
  created_at
  updated_at
```

采用单行快照，不拆事件表和卡片表。当前单次搜索只有少量官方源及有限卡片，拆表不会提供实际收益；当快照大小或跨任务事件查询成为可测瓶颈时再拆。

## 3. 恢复语义

- `completed/partial/timed_out/failed/cancelled/interrupted` 是终态，重启后原样读取。
- 启动时把 `pending/running` 改为 `interrupted`，追加一条 `job_interrupted` 事件和明确中文消息。
- 不自动重新执行搜索，不保存或恢复 `asyncio.Task`。
- 用户点击重新搜索会创建新 `jobId`；旧任务继续作为历史快照可查。
- 不在本阶段增加 TTL 清理。当前本地受信部署的搜索量不足以证明需要清理策略；引入清理前必须先固定保留期和审计需求。

## 4. 隐私与边界

- API 只返回现有公开 `cards`；完整 `cardGroups` 仅存服务端，用于订阅候选校验。
- 数据库查询先按 `jobId` 加载，再验证 `owner_user_id`；不得从客户端接受 owner。
- 用户删除后通过外键级联删除其搜索任务。
- JSON 反序列化失败按任务不存在处理，不执行其中任何代码或路径。
- 不复用管理员 `search_jobs`：该表是共享搜索工作台账，没有用户所有权和订阅候选契约。

## 5. 实施与门禁

### Phase A：schema 11

- 新表、owner 索引、状态约束、外键级联。
- 覆盖初建、v10 -> v11、幂等和回滚。

### Phase B：服务持久化

- 创建、每个源完成、任务终态时覆盖保存快照。
- 内存 miss 时从 SQLite 加载。
- lifespan 启动时执行 interrupted 收口。
- 覆盖 owner 隔离、完成任务重载、候选组重载和进行中任务恢复。

### Phase C：前端

- `interrupted` 加入终态、错误态和重试条件。
- 不新增页面、历史列表或自动重试控件。

### 最终门禁

- 分阶段定向测试通过。
- 根目录 `verify.ps1` 通过且受保护运行数据不因测试改变。
- 不修改 QDFCCKK 官方插件及版本。

## 6. 完成证据

截至 2026-07-17，本计划已完成：

- schema 11 已新增 `subscription_search_jobs` 单表快照、owner 索引和用户删除级联；真实 v10 数据库已在服务停机窗口完成迁移。
- 任务创建、每个官方源完成和最终状态均保存最近快照；完成任务重启后仍可查询公开卡片并使用原候选订阅。
- API 始终按当前登录用户验证 owner，公开响应不返回 `cardGroups/card_groups`；其他用户查询任务或候选继续得到 404。
- 启动时把 `pending/running` 收口为 `interrupted`，前端停止轮询、展示明确原因并允许重新搜索；外部搜索不会自动重放。
- 陈旧或冲突快照不会覆盖更新状态；损坏数值字段安全降级，损坏 JSON 按不存在处理；后台持久化失败会留可见事件且不会产生未处理任务异常。
- SQLite 连接显式关闭，后台搜索任务保留强引用；standalone 管线自检使用临时数据库和临时用户，不接触真实 `app.db`。
- 迁移前创建了一致性备份；迁移后全部既有业务表内容摘要、配置和 Cookie 文件摘要保持不变，`PRAGMA integrity_check` 为 `ok`，外键违规为 0。

验证结果：

- Phase 3 后端集中回归：51 passed；`backend/scripts/check_subscription_search_pipeline.py` 通过。
- 最终 `verify.ps1`：后端 296 passed / 5 skipped；22 个插件 validator 全部通过；前端 47 passed；npm audit 0 漏洞；lint/build 和 runtime import smoke 通过。
- 视觉报告：`frontend/visual-diff/output/2026-07-17_07-28-24-805/report.md`，39 场景，整体 99.86%，最低 98.09%，PASS。
- 最终保护检查：`Verification passed without runtime data changes.`
- 本阶段未修改 QDFCCKK 官方插件及其版本。
