# LegadoHub 公网授权夜间迭代报告（2026-07-20）

> 历史说明：本文下方只记录当时的 r4 构建。此后部署契约已调整为默认将 `data`、`config`、`generated`、`runtime` 绑定到宿主；第三方插件仍由镜像提供种子，并可通过可选 override 绑定宿主目录。

## 1. 结论

公网受邀用户授权的应用层实现、公共/管理员双端口隔离、LAN Docker 部署、真实官方插件调用、攻击面抽查、加密备份与隔离恢复、完整仓库门禁均已完成并通过。

当前发布判定：

- **LAN/staging：通过，可进入真实安卓 Reading 验收。**
- **正式公网：暂不放行。** 正式域名 TLS、真实 WAF/CDN 限流、安卓 Reading 和外部主动扫描仍为 `NOT EVALUATED`。

本轮未修改 `QDFCCKK` 官方插件源码，所有真实起点验证均使用已同步到宿主的插件，并通过临时 CookieStore 副本运行。

## 2. Phase A-G 交付状态

### Phase A：契约与边界

- 上位产品文档与订阅所有权文档已同步为“个人授权码 + 用户 Session”。
- Reading 仍是主要阅读端；Console 只承担订阅和运维控制面。
- 匿名仅允许健康检查、书源 manifest 和授权兑换；阅读、评论与订阅均需身份。

### Phase B：授权码、Session 与迁移

- 普通用户使用服务端生成的 `LH1` 个人授权码，明文只展示一次。
- 授权码只兑换 Session；Web 使用 HttpOnly Cookie，Reading 使用 Bearer。
- 数据库只保存 Session SHA-256；单用户最多 3 个 Session，并发裁剪在 `BEGIN IMMEDIATE` 内完成。
- schema v12 -> v13 清空 7 个旧 Session，用户和业务表计数保持不变。
- 管理员旧 base64 配置迁移到 PBKDF2 哈希；迁移 marker 先成为唯一真相，文件清理失败时不会重新应用旧密码。
- 禁用管理员、未知用户名和错误密码统一返回同一 401，避免账号枚举。

### Phase C：Reading 数据面

- `/api/legado/*` 与 `/api/subscribe/legado/*` 阅读接口统一要求用户身份。
- 普通用户只能访问 `legadohub_ai_aggregate` 虚拟源；直接 App/Web/第三方插件 ID 返回 404，且不执行插件。
- Reading 搜索、详情、目录、正文和评论保持只读，不隐式创建订阅或任务。
- 搜索、章节和评论配置用户级速率/并发上限；评论分页和参数放大输入有固定边界。
- 原生 `loginUi` 只有在 `/api/auth/access/me` 明确返回 username 后才判定登录成功。

### Phase D：Console

- 公共 `8765` 登录页只显示个人授权码；管理 `8766` 登录页只显示管理员用户名和密码，不再在同一页面切换身份模式。
- 用户创建/重置授权码只展示一次；禁用、重置和撤销立即清理 Session。
- 登录 mutation 等待 `/auth/me` 返回明确身份后才完成，修复成功登录后偶发回弹登录页的竞态。
- 即使管理员 Cookie 因同主机不同端口被浏览器同时携带到 `8765`，公共前端仍按普通用户入口渲染，管理页面和 API 在服务端也不存在。

### Phase E：部署安全

- 应用支持精确 Trusted Host、固定 public base URL、可信代理、Origin/CSRF、安全响应头和 `no-store`。
- 容器以 `legadohub` 非 root 用户运行，根文件系统只读，`CapDrop=ALL`、`no-new-privileges`、PID/CPU/内存和日志轮转已配置。
- 同一个 Uvicorn 进程绑定 `8765/8766` 两个 socket，并按 ASGI 本地端口分发两个独立 FastAPI 应用；只有公共应用持有 lifespan，不会重复启动订阅、Ping 或词库后台任务。
- `8765` 默认只绑定回环；LAN 验收绑定精确 LAN 地址。管理员 `8766` 按产品决定默认绑定 `0.0.0.0`，外部防火墙、转发、TLS 和管理 ACL 由部署方负责。
- 公共 `8765` 不注册管理员认证、`/api/info`、Console API、OpenAPI 或管理 SPA；管理 `8766` 不注册授权码兑换。Browserless 仅内部 `expose`，无宿主 3000 映射。
- 后续镜像只打包第三方插件；官方插件从构建上下文排除并由宿主只读挂载。第三方宿主覆盖使用独立扫描目录：空目录保留镜像插件，同 ID 的第三方以宿主版本为准，且不能覆盖官方源。
- stock Caddy 不提供边缘 IP 限流。公共 Compose 现在要求 `LEGADOHUB_EDGE_RATE_LIMIT_VERIFIED`，未配置真实 WAF/CDN 时直接拒绝渲染。
- Caddy 使用可信代理链解析 `{client_ip}`，避免接入上游 WAF 后丢失真实客户端 IP。

### Phase F：攻防与真实调用

- 自动化覆盖认证绕过、重复 Authorization、IDOR、插件直读、SQL/JSON/XSS/路径/Host/Forwarded/Origin/CSRF/SSRF 和参数放大。
- 从第二台 LAN 主机完成书源导入、授权码兑换、明确身份、Bearer 搜索和退出闭环。
- LAN 运行态 smoke 结果：普通用户控制面 403、无效 Bearer 不回退 Cookie、未知字段/对象/重复参数 422、路径遍历 404、伪造 Host 400、重复 Authorization 401。
- 真实 App/Web 插件调用结果见第 5 节。

### Phase G：最终门禁

- 完整 `verify.ps1` 通过。
- Docker 冷启动、重启持久化、加密备份解密和隔离恢复通过。
- 保护路径验证未改写订阅、共享书和章节任务；官方 Cookie 启动前后解析对象一致，仅 JSON 重序列化改变字节摘要。

## 3. 完整门禁结果

第三方覆盖合并改动后最终重跑时间：2026-07-20 11:52-12:00（Asia/Shanghai）。

- 后端：`362 passed, 5 skipped`。
- 攻击矩阵 + 原生书源登录契约定向复验：`10 passed`。
- Python 依赖：无损坏依赖。
- 插件 validator：22 个全部 `OK`。
- 前端依赖审计：`0 vulnerabilities`。
- 前端测试：14 files / `68 passed`。
- ESLint、TypeScript 和生产构建：通过。
- Runtime import：通过。
- 视觉比较：45/45 场景，整体相似度 `100.00%`，要求 `98%`，结果 `PASS`。
- 运行数据保护：验证前后无变化。
- 视觉报告：`frontend/visual-diff/output/2026-07-20_03-59-46-351/report.md`。

已知非阻塞警告：Starlette TestClient、websockets 旧接口弃用提示，Windows Proactor/curl_cffi selector thread 提示，前端主 chunk 约 607 KB。

## 4. LAN Docker 验收

目标主机：`192.168.31.161`，仅受信局域网访问。

- 当前镜像：`legadohub:nightly-20260720-0050-r4`。
- r4 构建早于插件外置规则，仍包含当时的官方插件；当前运行容器未被本轮配置修改。新规则从下一次镜像构建开始生效。
- 镜像 ID：`sha256:5c64f8dc4b1b92ff2bd7fc439b65b7f3903261194af028bc2b74e7c6ba9b48b7`。
- 容器：`running/healthy`，实际 UID/GID 为 `1000:1000`，只读根，`Privileged=false`、`CapDrop=[ALL]`、`no-new-privileges=true`。
- 监听：公共入口 `192.168.31.161:8765`，管理员入口 `0.0.0.0:8766`；容器内同一进程监听两个端口，3000 未映射到宿主。
- Windows LAN 客户端 TCP 实测：`8765=true`、`8766=true`、`3000=false`。
- 空第三方宿主目录真实挂载探针：镜像内置插件 `20` 个、override 插件 `0` 个，内置插件保持可见；单元回归同时验证同 ID 宿主覆盖和官方源不可覆盖。
- 路由隔离实测：公共端管理员登录/Console API/OpenAPI/管理 SPA 均为 404；管理端授权码兑换为 404，未登录 Console API 为 401；书源 manifest 只包含 `8765`。
- 真实重启后容器重新进入 `healthy`，两个入口仍分别返回 `public/admin`，路由矩阵保持不变。
- 切换前后和重启后：用户 2、Session 0、订阅 0、搜索任务 0、聚合书/章节任务 0；`integrity_check=ok`，配置摘要和 2 份 Cookie 的规范化摘要均保持一致。
- SQLite 文件级 SHA-256 会随 WAL/checkpoint 布局变化，因此不作为唯一数据一致性依据；业务表计数、完整性、配置和 Cookie 规范化摘要才是本轮保护判据。
- 容器日志敏感值扫描：Authorization、Cookie、Session、授权码、密码和起点令牌模式均为 0 命中。
- 真实 Edge/Playwright 在 1440px 和 390px 视口验证：公共页只有授权码，管理页只有用户名/密码；无身份切换 Tab、横向溢出、控制台错误或失败网络请求。
- `lan-reading-test` 用于后续手机验收；授权码只保存在服务器 `/home/moyue/.config/legadohub/lan-reading-test.access-code`，权限 600，未写入报告或日志。
- 当前 r4 从 Windows LAN 客户端真实复验：授权兑换 200、明确身份成立、Bearer Reading 搜索 200、退出 200、旧 Bearer 随即 401；结束后 Session、订阅和搜索任务均为 0，数据库完整性为 `ok`。
- Playwright 真实浏览器完成 Console 登录，进入 `/console` 后停留 2.5 秒未回弹；退出后 `/api/auth/me` 明确未登录。

服务器根盘仍为 98%，可用约 620 MB。未执行 Docker prune，未拉取新镜像；r4 基于已有 r3 增加小型覆盖层，未安装或清理 Docker 工具。

## 5. 真实起点插件验证

验证书籍：《天命之上》，目录 1016 章。

### App 插件

- 登录：`authenticated=true`，且存在明确身份；`appTokenReady=true`。
- 搜索：20 条，精确命中目标书。
- 免费章：选择目录中标准免费章，正文 7436 字符，无 `U+FFFD`、无“设备信息错误”、非预览。
- VIP：最新未购章返回 182 字预览，`previewOnly=true`、`isPaid=true`、`authRequired=true`。
- 本章说：已知章节汇总总数 389，章末返回 10 条，无 debug error。

### Web 插件

- 登录：`authenticated=true`，且存在明确身份。
- 搜索：20 条，精确命中目标书。
- 目录：1016 章。
- 免费章：同一标准免费章正文 6932 字符，无乱码、非预览。

调用使用 `/tmp` 临时 CookieStore；真实 Cookie 文件解析对象前后完全相同。

## 6. 备份与恢复证据

最终脱敏证据索引：

- 文件：`/home/moyue/.local/share/legadohub/backups/cutover-20260720-015322/acceptance-final-20260720.json`
- SHA-256：`f5cf321c82c4c581aea88ba8ab4dd53f01b20e5950f63509866e42eac688089b`
- 内容仅包含数据库计数/完整性、容器安全属性、端口投影、Cookie 规范化 SHA-256 与布尔匹配结果，不包含 Cookie、授权码、Session 或密码值。

### 迁移前完整备份

- 文件：`/home/moyue/.local/share/legadohub/backups/legadohub-predeploy-full-20260720-0045.tar.gz.gpg`
- SHA-256：`103e6a4ace6748bde0b6a44e2cd51dfdd418b3b80b9e4afb58d69d7a938d1e15`

### 切换前停机态备份

- 文件：`/home/moyue/.local/share/legadohub/backups/cutover-20260720-015322/legadohub-cutover-20260720-015322.tar.gz.gpg`
- SHA-256：`af418191e49b20118d5d2a801c6ae8c2a9448d395b94a0582e009ca2c915a909`
- 实际解密：`integrity=ok`、schema 12、用户 1、Session 7。

### 迁移后备份

- 文件：`/home/moyue/.local/share/legadohub/backups/legadohub-postmigration-20260720-085611.tar.gz.gpg`
- SHA-256：`e6dc2450078f2b81fbd2ddee5f39ffaec4948618b06c1d6312bc3cd12d8aadad`
- 实际解密：`integrity=ok`、schema 13、用户 2、Session 0。

恢复演练在 `--network none`、非 root、只读根、`CapDrop=ALL` 的一次性容器中完成：备份解密、v12 -> v13、管理员登录、创建授权用户、授权兑换和退出均通过。临时容器和明文恢复目录已删除，生产容器全程健康。

备份密钥与密文分离，密钥文件权限 600；报告不包含任何秘密值。

## 7. NOT EVALUATED

以下证据必须在正式环境或真实安卓设备补齐，当前不能声称通过：

现场探测确认本机和 LAN Linux 服务器都没有 `adb`、`nmap`、`sqlmap`、`zap`、`schemathesis` 或 `mitmproxy`，也没有可确认的真实安卓设备；本轮未为补报告而向磁盘紧张的服务器安装工具。

服务器现有 SafeLine 配置未包含 LegadoHub `8765/8766` 上游，当前也没有 Caddy 容器或进程；因此不能把其他站点已有的 WAF/TLS 误算作本项目证据。

1. 正式域名 DNS、真实证书、HTTP -> HTTPS、HSTS 和公网 80/443 扫描。
2. WAF/CDN 的真实 IP/连接限流、429、真实客户端 IP 传递和重启窗口保持。
3. 真实安卓 Reading 导入、原生登录 UI、授权码明文清理、CookieJar 打开 Console、重启持久化、撤销和重新授权。
4. Reading 更新/重新导入后 Login Header 的保留或清理行为。
5. 独立安全工作站的 ZAP、SQLMap、Schemathesis 和 nmap 报告。
6. 正式公网环境的 Browserless 内部网络和云防火墙扫描；当前生产选择嵌入 Chromium。

## 8. 发布决定与下一步

当前不更新正式版本号、不提交、不推送、不开放公网。原因不是代码门禁失败，而是第 7 节外部验收证据尚未产生。

下一步按顺序执行：

1. 配置正式域名和 WAF/CDN，完成限流与 TLS 验收。
2. 从真实安卓 Reading 使用服务器已保存的 LAN 测试授权码完成 14 项客户端闭环。
3. 在一次性 staging 数据库和虚拟 CookieStore 上运行外部安全工具。
4. 复核报告后再运行一次最终门禁，随后决定版本、提交和推送。
