# fanqie_local — 番茄小说（本地下载器桥接）

通过本地运行的 [Tomato-Novel-Downloader](https://github.com/zhongbai2333/Tomato-Novel-Downloader)
Web API 接入番茄小说内容，绕开对番茄官方服务器的直连请求。

---

## 前置条件

1. 在本机启动番茄下载器 Web UI 模式：

   ```sh
   # 无密码
   Tomato-Novel-Downloader.exe --server

   # 有密码（推荐）
   Tomato-Novel-Downloader.exe --server --password 你的密码
   # 或
   TOMATO_WEB_PASSWORD=你的密码 Tomato-Novel-Downloader.exe --server
   ```

2. 默认监听 `http://127.0.0.1:18423`。这只允许与下载器处于同一网络命名空间的进程访问。
   若 LegadoHub 在 Docker 中运行，下载器还必须监听宿主机可达地址：

   ```sh
   TOMATO_WEB_ADDR=0.0.0.0:18423 Tomato-Novel-Downloader.exe --server
   ```

   同时将 `FANQIE_LOCAL_BASE` 指向宿主机地址；仅把插件地址改成
   `host.docker.internal`、但下载器仍监听 `127.0.0.1` 是无法连接的。

---

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FANQIE_LOCAL_BASE` | `http://127.0.0.1:18423` | 下载器地址 |
| `FANQIE_LOCAL_PASSWD` | 空 | 下载器密码（`--password` 参数对应值） |
| `FANQIE_LOCAL_TIMEOUT` | `900` | 等待整本下载完成的超时秒数 |

LegadoHub Docker 部署时可在 `docker-compose.yml` 里加：

```yaml
environment:
  FANQIE_LOCAL_BASE: "http://host.docker.internal:18423"
  FANQIE_LOCAL_PASSWD: "你的密码"
```

---

## 工作原理

```
Reading 搜索/订阅
  → fanqie_local.search() → 调下载器 /api/search，并直接解析 items[].raw
  → fanqie_local.detail() → 用户打开详情时调下载器 /api/preview/:book_id
  → fanqie_local.toc()    → 触发/等待整本 txt 落盘 → 解析章节列表
  → fanqie_local.chapter() → 从落盘 txt 按章节 index 切出内容返回
```

**整本下载完成才转换**：`toc()` 和 `chapter()` 都依赖本地 txt 文件。
若文件不存在，插件会向下载器发起下载 job 并轮询等待完成（最长 `FANQIE_LOCAL_TIMEOUT` 秒）。
文件一旦落盘，后续访问直接读本地缓存，不再重下。

---

## 并发与代理

- `proxy.mode: never`：本地请求永远不走 LegadoHub 全局代理。
- `rateLimit.perHostConcurrency: 1`：宿主对下载器的 API 调用最多 1 并发。
  下载器本身也限制同时只有 1 个活跃下载 job，不会堆积。
- 如需同时下载多本书，需在下载器侧调整（目前下载器设计为串行队列）。

---

## 验收状态

| 阶段 | 状态 | 说明 |
|------|------|------|
| 静态契约 | ✅ | validate_source_plugin 通过 |
| fixture smoke | ⚠️ 未评估 | 需要本地下载器实例才能录制 fixture |
| 真实链路 | ⚠️ 未评估 | 需要本地下载器运行环境 |

> fixture smoke 依赖真实下载器响应，无法在离线环境录制。
> 验收时请在有下载器的机器上执行真实链路测试，并将响应保存到 `smoke/fixtures/`。

---

## 已知限制

- 搜索依赖下载器的 `official-api` feature；若以 `no-official-api` 模式构建，搜索返回空。
- 章节顺序从 txt 文件解析，依赖番茄下载器输出的格式（`第x章 标题` 或序章/番外等）。
  若格式变化导致解析失败，全文会作为单章返回。
- 封面图来自下载器 `/api/preview-cover-by-book/:book_id`，需下载器已缓存封面才可用。
