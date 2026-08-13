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
  → fanqie_local.toc()    → 用 /api/status 校验下载器 → 确认 job 已完成 → 扫描 /api/library → 解析成品 EPUB/TXT
  → fanqie_local.chapter() → 从成品文件按章节 index 返回正文
  → chapter_reviews()      → 从 EPUB 的“章节名 - 段评”辅助页返回段落短评
```

**整本下载完成才转换**：`toc()`、`chapter()` 和 `chapter_reviews()` 只读取状态为
`done` 的下载 job 对应成品。最终文件通过 `/api/library` 定位、通过 `/download/<rel_path>`
读取，不直接访问 `/api/status.save_dir` 暴露的主机绝对路径。

插件优先选择 EPUB，因为 Tomato 只在完整 EPUB 中保存段评、头像和评论图片；TXT 仅作为
既有成品的正文兼容格式。文件下载后会在 Hub 进程内缓存解析结果，不会按章重复下载整本。

---

## 下载器段评配置

`official-api` 构建只表示下载器具备抓取段评的代码能力；还必须在 `config.yml` 中实际开启：

```yaml
novel_format: epub
enable_segment_comments: true
segment_comments_top_n: 10
download_comment_images: true
download_comment_avatars: true
```

配置变更不会给已经生成的 EPUB 补数据。旧 EPUB 没有“章节名 - 段评”页时，需要删除或覆盖
旧成品并重新下载。Hub 仍会正常导入正文，但短评结果为空，调试信息会明确提示重新生成 EPUB。

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
- 目录和正文优先按 Tomato 的 `chapter_XXXXX.xhtml` 解析；简介、分卷、可见目录和段评辅助页不会被误识别为章节。
- 段评来自下载时写入 EPUB 的快照，最多只有 `segment_comments_top_n` 条；它不是实时评论 API。
- 当前 Hub 短评结构会保留评论文字、作者、时间和点赞数。EPUB 内嵌头像/评论图片尚不作为公开 URL 暴露，避免把 ZIP 相对路径或不受控数据 URL 直接交给客户端。
- 封面图来自下载器 `/api/preview-cover-by-book/:book_id`，需下载器已缓存封面才可用。
