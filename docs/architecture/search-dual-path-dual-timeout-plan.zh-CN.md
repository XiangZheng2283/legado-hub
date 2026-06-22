# 搜索双路径、官方源接入与双超时设计

> 状态：执行方案  
> 日期：2026-06-20  
> 范围：legado-hub 搜索系统、AI 聚合、官方源、缓存、前端  
> 结论：直接重构，废弃旧缓存先回方案

---

## 1. 普通搜索路径

### 1.1 接口

```
POST /api/console/search-jobs
GET  /api/legado/search
```

### 1.2 行为

1. 始终启动真实搜索，不做缓存先回
2. 根据设置决定是否接入官方源
3. 第三方源始终参与
4. 某站点超时/失败/无返回时，用该站点历史缓存补位
5. 只返回 `displayType="source"` 的结果

### 1.3 官方源接入规则

设置项：`search.officialSourceInNormalSearch`（布尔，默认 `false`）

- 关闭时：普通搜索只搜第三方源
- 开启时：普通搜索同时搜第三方源和官方源
- 官方源命中结果额外加权 `+50` 分

---

## 2. AI 聚合搜索路径

### 2.1 接口

```
POST /api/console/search/aggregate
```

### 2.2 行为

1. 独立路径，不与普通搜索共用结果表
2. 内部先跑普通源搜索阶段
3. 普通源阶段完成后，进入聚合阶段
4. 最终只返回 `displayType="aggregate"` 的结果
5. 进度区/日志区仍显示普通源搜索过程

### 2.3 主源选择策略

1. 优先使用官方源搜索结果生成聚合壳
2. 如果某本书官方源有命中，以官方源结果作为主源
3. 如果官方源无命中但第三方源有命中，从第三方高权重结果中选出主源生成聚合壳
4. 聚合结果一旦生成，不闪烁消失，只允许增强更新

### 2.4 聚合壳生成规则

```
primary_book_id_from_payload():
  1. 优先选官方源的 book_id
  2. 无官方源时，选 score 最高的第三方源 book_id
```

---

## 3. 缓存策略

### 3.1 废弃"缓存先回"

不再先查缓存再搜实时。

### 3.2 站点级缓存回退

1. 先真实搜索
2. 某站点超时/失败/无返回时，尝试该站点历史缓存结果补位
3. 缓存补位项标记 `freshness="cached"`
4. 若后续真实结果返回，覆盖该站点之前的 cached 结果

### 3.3 缓存表

继续使用 `book_search_cache`，TTL 7 天。

---

## 4. 双超时设计

### 4.1 源级双超时

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `sourceSoftTimeoutSeconds` | 6 | 软超时：无结果时先缓存补位，但真实搜索继续 |
| `sourceHardTimeoutSeconds` | 25 | 硬超时：标记 timeout，停止等待 |
| `overallTimeoutSeconds` | 120 | 全局总超时 |

### 4.2 行为

```
t=0:   源搜索开始
t=6s:  若无真实结果 → 尝试该源历史缓存补位 (freshness=cached)
       但该源真实搜索继续跑
t=25s: 若仍无真实结果 → 标记 timeout，停止等待
       若已有缓存补位则保留
       若后续真实结果返回 → 覆盖 cached，freshness 变为 live
t=120s: 全局超时，结束所有搜索
```

### 4.3 AI 聚合搜索超时

| 参数 | 值 |
|------|-----|
| 源搜索阶段 | 同普通搜索 (soft=6, hard=25) |
| `aggregateOverallTimeoutSeconds` | 180 |

---

## 5. 搜索匹配规则

### 5.1 混合匹配

不再让用户手动切换"按书名/按作者"。

### 5.2 权重

| 命中方式 | 权重 |
|----------|------|
| 书名完全命中 | +200 |
| 书名包含命中 | +100 |
| 作者完全命中 | +80 |
| 作者包含命中 | +40 |
| 书名+作者同时命中 | 额外 +50 |
| 官方源命中 | 额外 +50 |
| 站点缓存回退 | -30 |

---

## 6. 前端展示字段语义

### 6.1 普通书源结果

```json
{
  "displayType": "source",
  "freshness": "live|cached"
}
```

- `freshness=live`：获取时间显示绿色
- `freshness=cached`：获取时间显示灰色

### 6.2 AI 聚合结果

```json
{
  "displayType": "aggregate",
  "resultKind": "aggregate"
}
```

- 不显示 freshness
- 按钮文字为「聚合详情」

### 6.3 前端模式切换

搜索页新增两个按钮：
- 普通书源（默认）
- 书源聚合

### 6.4 设置页

新增配置项：
- 启用官方源参与普通搜索（布尔开关）

---

## 7. 接口定义

### 7.1 普通搜索

```
POST /api/console/search-jobs
```

请求：
```json
{"keyword": "剑宗外门", "page": 1, "sourceIds": null}
```

响应（轮询完成后）：
```json
{
  "jobId": "xxx",
  "status": "completed",
  "searchMode": "source",
  "sourceCount": 20,
  "completedCount": 20,
  "result": {
    "items": [
      {
        "displayType": "source",
        "freshness": "live",
        "name": "剑宗外门",
        "sourceId": "69shuba_com",
        "score": 226
      }
    ]
  }
}
```

### 7.2 AI 聚合搜索

```
POST /api/console/search/aggregate
```

响应（轮询完成后）：
```json
{
  "jobId": "xxx",
  "status": "completed",
  "searchMode": "aggregate",
  "result": {
    "items": [
      {
        "displayType": "aggregate",
        "resultKind": "aggregate",
        "name": "剑宗外门",
        "sourceId": "legadohub_ai_aggregate",
        "score": 227
      }
    ]
  },
  "debug": {
    "aggregatePhaseStarted": true,
    "aggregatePhaseCompleted": true
  }
}
```

### 7.3 轮询

```
GET /api/console/search-jobs/{job_id}
```

按 `searchMode` 返回对应结果。

---

## 8. 验证方案

1. 普通搜索（关闭官方源）：结果无官方源
2. 普通搜索（开启官方源）：结果有官方源，评分 +50
3. AI 聚合：官方源命中时以官方源为主源
4. AI 聚合：官方源无命中时第三方兜底
5. 站点缓存回退：soft timeout 后出现 cached，live 返回后覆盖
6. 官方源登录：不再因缺文件报错
