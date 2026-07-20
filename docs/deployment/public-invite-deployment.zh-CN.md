# 公网受邀用户部署与恢复手册

> 适用范围：单机、单后端进程、少量受邀用户。Reading/普通用户流量必须先经过已配置限流的 WAF/CDN，再进入 Caddy 的 80/443 和公共入口 8765；管理员入口独立监听 8766。8766 按产品决定默认绑定宿主 `0.0.0.0`，其防火墙、转发、TLS 与管理网段 ACL 由部署方负责。Browserless 3000 不直接开放。仓库使用 stock Caddy，它本身不提供本项目要求的边缘 IP 限流，不能单独作为公网放行依据。

## 1. 前置条件

- 已解析到服务器的正式域名，例如 `books.example.com`。
- 已在 Caddy 前配置 WAF/CDN 的 IP 连接与请求限流，并能传递可信的 `X-Forwarded-For`。认证入口至少限制为每 IP 5 次失败/10 分钟，通用 API 还需配置突发与并发上限。
- WAF/CDN 到 Caddy 必须使用 TLS 透传或 HTTPS 回源；不要用 HTTP 回源后伪造 `X-Forwarded-Proto=https` 绕过应用的 HTTPS 判断。
- 源站 IPv4/IPv6 的 80/443 只允许 WAF/CDN 的精确出口地址访问；其他来源直连源站 IP 必须被防火墙或安全组拒绝，避免绕过边缘限流和 Host 策略。
- 公网 TLS 最低为 1.2，推荐启用 1.3；拒绝 TLS 1.0/1.1 和弱密码套件，并为完整证书链、域名匹配、到期监控及自动续期保留验收证据。
- 不受信公网防火墙只允许公共 TCP 80/443；若启用 HTTP/3，再允许 UDP 443。管理员 8766 只能按部署方明确的管理来源、VPN 或前置代理策略放行，不能因为应用默认监听 `0.0.0.0` 就省略网络 ACL。
- Docker 与 Compose 由运维环境预先提供。本项目不会自动安装、升级或清理 Docker。
- 后端数据库、配置、Cookie、正文与生成物保存在容器可写层；替换或删除容器前必须完成加密备份，否则这些数据会永久丢失。
- 公网模式只支持单个 LegadoHub 后端容器；不要设置多副本。

## 2. 凭据与目录

Linux 宿主执行：

```bash
install -d -m 700 plugins/sources/official plugins/sources/thirdparty secrets
APP_UID="$(id -u)"
APP_GID="$(id -g)"
chown -R "$APP_UID:$APP_GID" plugins/sources/official plugins/sources/thirdparty
umask 077
printf '%s' '使用密码管理器生成的管理员密码' > secrets/admin_password.txt
chmod 600 secrets/admin_password.txt
```

创建不入库的 `.env`：

```dotenv
LEGADOHUB_PUBLIC_HOST=books.example.com
LEGADOHUB_ADMIN_PASSWORD_SECRET_FILE=/absolute/path/to/legado-hub/secrets/admin_password.txt
LEGADOHUB_APP_UID=<id -u 输出>
LEGADOHUB_APP_GID=<id -g 输出>
LEGADOHUB_OFFICIAL_PLUGINS_DIR=./plugins/sources/official
LEGADOHUB_THIRDPARTY_PLUGINS_DIR=./plugins/sources/thirdparty
LEGADOHUB_EDGE_TRUSTED_PROXIES=<WAF/CDN 到 Caddy 的精确出口 IP/CIDR>
LEGADOHUB_EDGE_RATE_LIMIT_VERIFIED=1
LEGADOHUB_ADMIN_BIND_ADDRESS=0.0.0.0
LEGADOHUB_ADMIN_PORT=8766
LEGADOHUB_ADMIN_BASE_URL=https://admin-books.example.com
LEGADOHUB_ADMIN_ALLOWED_HOSTS=admin-books.example.com
LEGADOHUB_ADMIN_ALLOWED_ORIGINS=https://admin-books.example.com
LEGADOHUB_ADMIN_TRUSTED_PROXIES=<管理员反向代理的精确出口 IP/CIDR>
```

`LEGADOHUB_APP_UID/GID` 必须填写实际执行部署用户的 `id -u` / `id -g` 结果，并与第三方插件目录的属主一致。Compose 的 bind mount 会覆盖镜像内目录权限；属主不一致时启动脚本无法初始化空目录，禁止通过把目录改成 777 解决。

官方插件不包含在 Docker 镜像中，启动前由部署方放入 `LEGADOHUB_OFFICIAL_PLUGINS_DIR`；目录为空时系统不会提供官方源。第三方插件以种子形式随镜像发布。设置 `LEGADOHUB_THIRDPARTY_PLUGINS_DIR` 并叠加 `docker-compose.plugins.yml` 后，该目录直接挂载到运行路径；首次为空时自动复制种子，非空时不覆盖任何宿主文件。镜像更新后若要采用新版种子，应先备份并人工清空或更新宿主目录。

`LEGADOHUB_EDGE_RATE_LIMIT_VERIFIED=1` 是发布门禁确认，不是限流实现。只有完成 WAF/CDN 配置并从独立客户端验证 429、连接上限和真实客户端 IP 后才能设置；直接填写该值绕过检查属于禁止发布。`LEGADOHUB_EDGE_TRUSTED_PROXIES` 只允许上游代理的精确出口地址，不得填写全部私网或 `0.0.0.0/0`。

`LEGADOHUB_ADMIN_BIND_ADDRESS=0.0.0.0` 只决定监听，不等于允许任意来源访问。管理员入口应使用独立域名/转发或受控管理网络；应用会按 `LEGADOHUB_ADMIN_BASE_URL`、Allowed Host、Allowed Origin 和 Trusted Proxy 再做精确校验。公共 Caddyfile 只反代 `legadohub:8765`，不得把公共域名转发到 8766。

仓库内置 Caddyfile 不提供 `admin-books.example.com` 的管理员反向代理。上面的管理员域名只是外部管理代理配置示例；部署方必须自行提供该转发与证书，或把 Admin Base URL/Host/Origin 改成实际受控管理入口。未配置外部管理代理时，不能把示例域名列为已验收能力。

启用第三方插件映射时，启动前执行 `test -w "$LEGADOHUB_THIRDPARTY_PLUGINS_DIR"`。检查失败时先修正属主，不要启动容器反复重试写入。

若使用 Browserless，另生成高强度随机值并写入受限 `.env`：

```dotenv
LEGADOHUB_BROWSERLESS_TOKEN=<random-secret>
```

禁止在 Compose、镜像、Git、日志或书源 JSON 中写入管理员密码、授权码、Session、Cookie 或 Browserless Token。

## 3. 配置检查与启动

先渲染配置，不启动容器：

```bash
docker compose -f docker-compose.yml -f docker-compose.public.yml config --quiet
```

嵌入 Chromium：

```bash
docker compose -f docker-compose.yml -f docker-compose.public.yml up -d --build
```

内部 Browserless：

```bash
docker compose -f docker-compose.yml -f docker-compose.browserless.yml -f docker-compose.public.yml up -d --build
```

外置第三方插件：

```bash
LEGADOHUB_THIRDPARTY_PLUGINS_DIR=/absolute/path/to/thirdparty \
docker compose -f docker-compose.yml -f docker-compose.plugins.yml -f docker-compose.public.yml up -d --build
```

首次启动完成并确认管理员可登录后，可以移除容器的管理员 secret 挂载；数据库已有管理员时不会再次使用该 secret。替换容器时必须先恢复数据库，或者重新挂载首次启动 secret。不要恢复旧 `auth.adminPasswordBase64`。

## 4. 发布验收

```bash
curl -fsS https://books.example.com/health
curl -I https://books.example.com/api/subscribe/legado/source
curl -i https://books.example.com/api/auth/login
curl -i https://books.example.com/api/console/status
curl -fsS https://admin-books.example.com/api/auth/entrypoint
docker inspect legadohub --format '{{.Config.User}} {{json .HostConfig.CapDrop}}'
docker inspect legadohub --format '{{json .HostConfig.LogConfig}}'
docker compose -f docker-compose.yml -f docker-compose.public.yml ps
```

必须确认：

- HTTP 自动跳转 HTTPS，认证 Cookie 包含 `Secure; HttpOnly; SameSite=Lax; Path=/`。
- TLS 1.2/1.3 握手和完整证书链通过；TLS 1.0/1.1 与弱套件握手失败；证书到期监控和自动续期已经实际演练。
- 伪造 `Host` 返回 400，伪造 `X-Forwarded-Host` 不改变书源中的 URL。
- 从公网无法连接 8765 和 3000。
- 不受信客户端直连源站 IPv4/IPv6 的 80/443 失败，只有声明的 WAF/CDN 出口可以回源；通过正式域名访问仍成功。
- 公共域名请求管理员登录、Console API、管理 SPA、SSE 和 OpenAPI 均为 404；管理员域名的 `/api/auth/entrypoint` 返回 `admin`。
- 8766 的实际可达来源与部署方声明的防火墙/转发 ACL 一致；从不受信公网不能绕过管理代理直连。
- 应用容器为非 root、`CapDrop=ALL`、日志轮转已启用。
- `backend/config`、Cookie 文件和数据库分别保持 700/600 权限。
- 匿名只能导入书源；搜索、详情、目录、正文和评论返回 401。
- WAF/CDN 的认证限流返回 429，且 Caddy 传给应用的客户端 IP 不是上游代理自身地址；重启 LegadoHub 不会清空边缘限流窗口。

## 5. LAN 手机验收

仅在受控局域网临时测试时，可把 `.env` 中 `LEGADOHUB_BIND_ADDRESS` 设置为服务器的 LAN IPv4，并把 `LEGADOHUB_PUBLIC_BASE_URL`、Allowed Host/Origin 同步设置为该地址。管理员端口已经默认绑定 `0.0.0.0:8766`；若直接使用 LAN IP 访问，还要同步设置 `LEGADOHUB_ADMIN_BASE_URL`、Admin Allowed Host/Origin。公网模式下非 loopback 管理地址必须使用 HTTPS。测试结束后按正式防火墙/代理策略收口，不要用 `0.0.0.0:8765` 作为公网 Reading 部署方案。

Reading 导入地址：

```text
https://books.example.com/api/subscribe/legado/source
```

管理员入口：

```text
https://admin-books.example.com/console
```

验收流程：导入 -> 输入个人授权码 -> 明确显示用户名 -> 搜索已发布书 -> 目录 -> 全文/预览 -> 本章说 -> 服务重启后复读 -> 管理员撤销会话 -> 客户端变为未登录 -> 重新授权。

## 6. 加密备份

后端目录不映射到宿主，必须在停写窗口内从容器导出 SQLite 在线备份、配置和共享正文；备份文件必须在离开主机前加密。示例工具只是运维选择，不由项目自动安装：

```bash
backup_dir="$(mktemp -d)"
docker exec legadohub python -c "import sqlite3; src=sqlite3.connect('/app/backend/data/app.db'); dst=sqlite3.connect('/tmp/legadohub-app.db'); src.backup(dst); dst.close(); src.close()"
docker cp legadohub:/app/backend/data "$backup_dir/data"
docker cp legadohub:/tmp/legadohub-app.db "$backup_dir/data/app.db"
docker cp legadohub:/app/backend/config "$backup_dir/config"
docker cp legadohub:/app/backend/generated "$backup_dir/generated"
tar -C "$backup_dir" -czf /tmp/legadohub-backup.tar.gz .
gpg --symmetric --cipher-algo AES256 --output legadohub-backup.tar.gz.gpg /tmp/legadohub-backup.tar.gz
docker exec legadohub rm -f /tmp/legadohub-app.db
rm -rf "$backup_dir" /tmp/legadohub-backup.tar.gz
```

备份清单至少记录版本、时间、数据库 SHA-256、配置 SHA-256、Cookie 文件数量和共享书目录数量，不记录任何秘密值。

## 7. 隔离恢复演练

1. 在不复用生产容器、不复用生产端口的临时目录解密备份。
2. 使用独立 Compose project name 创建临时容器，将备份内容复制回容器内对应的 `/app/backend/data`、`config` 和 `generated` 路径后再启动。
3. 验证 schema、管理员登录、用户禁用/撤销、共享书目录和随机章节读取。
4. 验证日志与 API 不包含 Cookie、Authorization、授权码或内部绝对路径。
5. 删除隔离容器和演练目录前保存不含秘密的结果摘要。

不得把“生产容器内直接覆盖文件”当作恢复演练；正式恢复必须先停止写入并保留可回退副本。

## 8. 泄漏处置

- 普通用户授权码泄漏：重置该用户授权码，确认全部旧 Session 已撤销。
- 管理员密码泄漏：从可信终端修改密码，撤销管理员 Session，核查审计。
- 官方 Cookie 泄漏：在官方站点退出全部设备，清理宿主 CookieStore 后重新登录。
- Browserless Token 泄漏：生成新 Token并同时重启 Browserless 与应用。
- 主机或数据库泄漏：视为全部 Session、官方 Cookie 和管理员凭据失陷，整体轮换；Session 数据库只存哈希不等于主机失陷后仍安全。
