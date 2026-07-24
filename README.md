# LegadoHub

自托管小说聚合订阅服务，为 Reading / Legado 提供稳定的后端书源。

---

## 解决什么问题

使用 Reading 或 Legado 阅读小说的用户普遍面临书源不稳定的问题：单个书源频繁失效，更换书源需要重新搜索和登录，多人使用时各自维护一套书源，重复消耗时间和带宽。

LegadoHub 采用**服务端订阅聚合**模式：将书源维护和章节处理统一放在后端，管理员统一管理书源与用户，读者只需搜索、订阅和阅读。

核心设计：

- **共享书库**：每本书入库后成为全局共享资产，多人订阅同一本书共享一份章节缓存，各自独立管理进度
- **主源优先，候选补全**：官方源作为主源获取章节正文；当主源仅返回 VIP 预览时，自动从第三方候选源补全完整内容
- **后台持续处理**：章节从主源获取后按序缓存落盘，连载期间持续跟踪更新，不因单源状态波动丢失已有数据
- **关注点分离**：管理员一次性维护书源和用户，读者只需要搜索、订阅、打开阅读器

```
管理员安装插件、登录官方源 → 创建用户分配授权码
                ↓
用户搜索并订阅 → 服务端从主源抓取章节、候选源补全
                ↓
在 Reading / Legado 中导入聚合书源 → 直接阅读
```

---

## 快速开始

推荐使用 Docker Compose；不使用 Compose 时可直接跳到 [Docker CLI](#docker-cli)。

### 前提条件

一台安装了 Docker 的机器（NAS、VPS、本地均可），端口 `8765` 和 `8766` 空闲。

### 1. 准备目录

```bash
mkdir -p /opt/legado-hub && cd /opt/legado-hub
mkdir -p data config generated runtime plugins/sources/thirdparty plugins/sources/official
```

### 2. 下载 compose 文件

```bash
curl -fsSL -o docker-compose.yml \
  https://raw.githubusercontent.com/XziXmn/legado-hub/main/docker-compose.yml
```

编辑 `docker-compose.yml`，需要关注的部分：

| 配置项 | 说明 |
|--------|------|
| `PUID` / `PGID` | 宿主机的用户和组 ID（默认 `1000`，大多数场景无需修改） |
| `volumes` 左侧路径 | NAS 用户将相对路径替换为绝对路径（文件内已附群晖、飞牛等注释示例） |
| `ports` | 仅在端口冲突时修改左侧宿主端口 |

更换过 `PUID` / `PGID` 或旧书库属主不正确时，可执行一次完整修权：

```bash
LEGADOHUB_CHOWN_DATA=1 docker compose up -d --force-recreate legadohub
docker compose up -d --force-recreate legadohub
```

`docker compose restart` **不会**应用新的环境变量，不能用于这次迁移。

### 3. 启动

```bash
docker compose pull
docker compose up -d
```

首次拉取镜像较大（内含 Chromium），约数十秒后容器状态变为 `healthy`。

验证两个入口均可达：

```bash
curl -s http://127.0.0.1:8765/api/auth/entrypoint   # → "entrypoint":"public"
curl -s http://127.0.0.1:8766/api/auth/entrypoint   # → "entrypoint":"admin"
```

### 4. 获取管理员密码

首次启动自动创建账号 `admin`，高熵随机密码仅在日志中打印一次：

```bash
docker compose logs legadohub | grep -i password
```

若错过日志，执行重置：

```bash
docker compose exec -T legadohub \
  python /app/backend/scripts/reset_user_password.py --username admin
```

登录后建议前往 **设置 → 账户安全** 修改密码。

### 5. 初始配置

1. 打开管理后台 `http://服务器IP:8766`，使用 `admin` 登录
2. 安装书源插件（第三方插件随镜像附带；官方插件需放入 `plugins/sources/official/` 后重启容器）
3. 在「用户管理」创建普通用户，**立即保存授权码**（对话框关闭后不再显示明文）

### 6. 接入 Reading / Legado

在阅读器中通过以下地址添加书源：

```
http://服务器IP:8765/api/subscribe/legado/source
```

导入后在书源管理页启用本书源，即可进入搜索与阅读。从搜索结果进入书籍详情页即开始阅读，阅读器展现的正是经过服务端聚合处理后的章节列表。

### Docker CLI

不使用 Compose 时，在已经准备好数据目录的 `/opt/legado-hub` 中运行：

```bash
docker pull xzixmn/legado-hub:latest

docker run -d \
  --name legadohub \
  --restart always \
  --init \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add SETGID --cap-add SETUID \
  -p 8765:8765 -p 8766:8766 \
  -e TZ=Asia/Shanghai -e PUID=1000 -e PGID=1000 -e LEGADOHUB_CHOWN_DATA=0 \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  -v "$PWD/data:/app/backend/data" \
  -v "$PWD/config:/app/backend/config" \
  -v "$PWD/generated:/app/backend/generated" \
  -v "$PWD/runtime:/app/backend/runtime" \
  -v "$PWD/plugins/sources/thirdparty:/app/plugins/sources/thirdparty" \
  -v "$PWD/plugins/sources/official:/app/plugins/sources/official:ro" \
  xzixmn/legado-hub:latest
```

---

## 公网部署（VPS / 域名 / 公网 IP）

默认按**本机或受控局域网**设计：未配置公网地址时，阅读口只接受局域网 Host；公网客户端直接访问公网 IPv4 会被拒绝（`400 Host is not allowed`）。  
服务本身仍监听 `0.0.0.0`，容器可正常启动；需要的是登记**允许的公网 origin**。

### 公网地址优先级

```
控制台「设置 → 阅读 → 允许的公网地址」
  > 环境变量 LEGADOHUB_PUBLIC_BASE_URL
  > 仅局域网自动识别
```

- **部署时**：可在 `docker-compose.yml` 的 `environment` 里写入变量做首次引导  
- **之后**：在管理后台保存「允许的公网地址」即可覆盖变量，**无需重建容器**  
- **局域网访问**：仍按实际访问 Host 生成内网书源（与公网为双源身份，见下文）

### 1. 环境变量（可选，首次引导）

在 `docker-compose.yml` 的 `legadohub.environment` 中增加（域名或公网 IP 均可）：

**域名 + HTTPS（推荐，经反代终止 TLS）**

```yaml
- LEGADOHUB_PUBLIC_BASE_URL=https://book.example.com
- LEGADOHUB_ALLOWED_HOSTS=book.example.com
- LEGADOHUB_ALLOWED_ORIGINS=https://book.example.com
# 反代所在网段（Docker 网桥 / 本机反代按实际填写）
- LEGADOHUB_TRUSTED_PROXIES=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.1/32
```

**公网 IP + 直连 HTTP（无域名时）**

```yaml
- LEGADOHUB_PUBLIC_BASE_URL=http://203.0.113.10:8765
- LEGADOHUB_ALLOWED_HOSTS=203.0.113.10
- LEGADOHUB_ALLOWED_ORIGINS=http://203.0.113.10:8765
```

说明：

| 项 | 要求 |
|----|------|
| origin 格式 | 必须 `http://` 或 `https://` 开头，**不要带路径**（如 `/api`） |
| 端口 | 非 80/443 时必须写在 origin 与访问地址中 |
| 一致性 | 浏览器、Reading 导入地址、白名单 origin 的协议/主机/端口须一致 |
| 固定 HTTPS | 配置了 `https://` 的 `LEGADOHUB_PUBLIC_BASE_URL` 时，阅读口会要求 HTTPS |

修改环境变量后需重新创建容器才能生效：

```bash
docker compose up -d --force-recreate legadohub
```

### 2. 控制台设置（推荐，可覆盖变量）

1. 从**可访问的入口**打开管理后台（首次可先在本机/内网用 `http://服务器局域网IP:8766`，或已放行防火墙的 `http://公网IP:8766`）
2. 登录后打开 **设置 → 阅读 → 公网访问白名单 → 允许的公网地址**
3. 填入与对外访问一致的 origin，例如：
   - `https://book.example.com`
   - `http://203.0.113.10:8765`
4. 保存后立即生效；此后**设置优先于** `LEGADOHUB_PUBLIC_BASE_URL`

### 3. 防火墙与反代建议

| 端口 | 用途 | 建议 |
|------|------|------|
| `8765` | 用户 / Reading 书源 | 可经域名反代或公网放行；务必配合授权码 |
| `8766` | 管理后台 | **不要对全网裸奔**；限制来源 IP、VPN 或仅内网 |

TLS、反向代理（Caddy / Nginx / Cloudflare 等）由部署者自行配置；应用不内置公网证书与反代。

### 4. 接入书源（公网）

在 Reading / Legado 中导入：

```
https://你的域名/api/subscribe/legado/source
# 或
http://你的公网IP:8765/api/subscribe/legado/source
```

须与已登记的公网 origin 一致。用该地址打开阅读入口并更新书源后，生成的链接才会是公网地址。

### 5. 公网与局域网双源

| 导入方式 | 书源身份（示意） |
|----------|------------------|
| 公网域名 / 公网 IP | `LegadoHub`（公网） |
| 局域网 IP | `LegadoHub-LAN`（内网，名称带「·内网」） |

两套可同时存在；授权与进度按书源分开。日常建议按当前网络只启用对应那一套再搜索。

### 6. 自检

```bash
# 容器健康
docker compose ps

# 入口（本机）
curl -s http://127.0.0.1:8765/api/auth/entrypoint
curl -s http://127.0.0.1:8766/api/auth/entrypoint

# 公网（将地址换成你的 origin）
curl -sI https://book.example.com/api/auth/entrypoint
```

若返回 `400 Host is not allowed`，说明当前 Host 未进入白名单（设置或环境变量），或协议/端口与登记不一致。

---

## 两种使用方式

导入聚合书源后，Reading / Legado 提供两种使用方式：

| 方式 | 说明 |
|------|------|
| **直接搜索第三方源** | 无需订阅，但需先用授权码登录；随后可在阅读器中直接搜索启用中的第三方书源。搜索结果独立显示，阅读器按常规流程获取章节。适合临时阅读。 |
| **订阅后阅读共享库** | 在书源界面输入授权码登录后，可以进入订阅控制台搜索并创建订阅。订阅书籍的章节由服务端持续处理：主源获取正文，候选源补全 VIP 预览，结果缓存落盘。优势：即使主源与第三方源后续不稳定，已处理的章节也始终可读。 |

**两者可以混合使用**：搜索结果中既包含第三方源的实时结果，也包含已入库的共享库聚合条目。

---

## 功能

| 功能 | 说明 |
|------|------|
| 共享书库 | 每本书入库后为全局资产，多人订阅共享一份章节缓存 |
| 主源优先，候选补全 | 官方源为主源获取章节；主源仅有 VIP 预览时，自动从第三方候选源补全正文 |
| 自动更新 | 连载期间持续检查更新，新章节按序抓取处理 |
| 邀请制多用户 | 管理员创建用户并分配独立授权码，互不干扰 |
| 入口分离 | `8765` 面向用户与阅读器，`8766` 面向管理员（建议防火墙限制来源） |

---

## 常见问题

<details>
<summary>为什么在 Reading 中搜不到刚订阅的书？</summary>

Reading 仅展示已发布且具备可读章节的书籍。请先在 Web 控制台「我的书库」确认至少已有可读章节并已发布。
</details>

<details>
<summary>为什么部分章节仅有预览？</summary>

服务不会绕过目标站的付费规则。当主源账号无完整权限、且所有候选源也未能补全时，章节可能仅保留预览内容。
</details>

<details>
<summary>书源可达，正文仍然获取失败？</summary>

“可达”仅表示网络连通，不保证页面结构、登录态或章节权限有效。请以书籍详情页的具体错误信息为准。
</details>

<details>
<summary>多个用户可以订阅同一本书吗？</summary>

可以。系统为每本书维护一份共享章节数据，各用户独立保存订阅关系与阅读进度。
</details>

<details>
<summary>忘记管理员密码？</summary>

```bash
docker compose exec -T legadohub \
  python /app/backend/scripts/reset_user_password.py --username admin
```

此命令生成新密码并撤销该管理员的所有现有会话。
</details>

<details>
<summary>第三方插件目录被清空了？</summary>

重启时若目录为空，入口脚本会从镜像种子恢复默认第三方插件。本地的自定义修改无法恢复，除非有备份。
</details>

<details>
<summary>公网 VPS 上提示 Host is not allowed？</summary>

未配置公网白名单时，阅读口会拒绝公网 Host。请设置环境变量 `LEGADOHUB_PUBLIC_BASE_URL`（及配套 `ALLOWED_HOSTS` / `ORIGINS`），或在管理后台「设置 → 阅读 → 允许的公网地址」登记与访问一致的 origin（可用域名或公网 IP）。详见 [公网部署](#公网部署vps--域名--公网-ip)。
</details>

---

## 安全与使用边界

- 默认面向本机或受控局域网部署。公网访问须登记允许的公网 origin（控制台设置优先于环境变量），详见 [公网部署](#公网部署vps--域名--公网-ip)。
- TLS、反向代理、防火墙与管理口（`8766`）暴露范围由部署者负责；不提供开放注册与匿名阅读。
- 请仅在有权访问和处理相应内容的前提下使用，并遵守目标站点服务条款与当地法律法规。
- 本项目并非 Legado 官方项目，不保证第三方书源的持续可用性。

---

## 开发者入口

| 主题 | 位置 |
|------|------|
| 仓库结构与本地启动 | [AGENTS.md](AGENTS.md) |
| 书源插件开发规范 | [docs/architecture/source-plugin-contract.zh-CN.md](docs/architecture/source-plugin-contract.zh-CN.md) |
| 插件编写教程 | [docs/skills/book-source-craft/README.md](docs/skills/book-source-craft/README.md) |
| 产品边界与设计原则 | [docs/PRODUCT.md](docs/PRODUCT.md) |
| 全量校验 | `verify.ps1` |

Windows 本地开发：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
.venv/Scripts/python.exe -m playwright install chromium
Set-Location frontend
npm install
npm run build
Set-Location ../backend
../.venv/Scripts/python.exe -m app.server --host 0.0.0.0 --public-port 8765 --admin-port 8766
```

或直接运行 `.\start.bat`。

---

## 贡献

问题反馈与功能建议请提交至 [GitHub Issues](https://github.com/XziXmn/legado-hub/issues)。

---

## 友情链接

- [LINUX DO](https://linux.do/)

---

## 许可

[MIT License](LICENSE)。源码、文档与仓库附属资源均按 MIT 授权，可自由使用、修改、分发与商用，须保留版权声明。

---

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docker Image](https://img.shields.io/badge/Docker-xzixmn%2Flegado--hub-2496ED?logo=docker)](https://hub.docker.com/r/xzixmn/legado-hub)
[![GitHub](https://img.shields.io/badge/GitHub-XziXmn-181717?logo=github)](https://github.com/XziXmn/legado-hub)
