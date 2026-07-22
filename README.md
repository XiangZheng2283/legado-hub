<div align="center">

# LegadoHub

**自托管小说聚合订阅服务**

面向 [Reading](https://github.com/hectorqin/reader) / [Legado](https://github.com/gedoor/legado) 的书源与订阅后端：统一维护书源与账号，后台整理章节，日常阅读仍在阅读器中完成。

<!-- Badge Row 1: Core Info -->
[![GitHub](https://img.shields.io/badge/GitHub-XziXmn-181717?logo=github)](https://github.com/XziXmn/legado-hub)
[![Docker Image](https://img.shields.io/badge/Docker-xzixmn%2Flegado--hub-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/xzixmn/legado-hub)
[![Version](https://img.shields.io/badge/version-latest-orange)](https://hub.docker.com/r/xzixmn/legado-hub)

<!-- Badge Row 2: Tech Stack -->
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![Platform](https://img.shields.io/badge/platform-amd64%20%7C%20arm64-475569)](https://hub.docker.com/r/xzixmn/legado-hub)

<!-- Badge Row 3: Platforms -->
[![Windows](https://img.shields.io/badge/Windows-0078D6?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4OCA4OCI+PHBhdGggZmlsbD0iI2ZmZiIgZD0iTTAgMGgzOXYzOUgweiIvPjxwYXRoIGZpbGw9IiNmZmYiIGQ9Ik00OSAwaDM5djM5SDQ5eiIvPjxwYXRoIGZpbGw9IiNmZmYiIGQ9Ik0wIDQ5aDM5djM5SDB6Ii8+PHBhdGggZmlsbD0iI2ZmZiIgZD0iTTQ5IDQ5aDM5djM5SDQ5eiIvPjwvc3ZnPg==)](https://github.com/XziXmn/legado-hub)
[![Linux](https://img.shields.io/badge/Linux-FCC624?logo=linux&logoColor=black)](https://github.com/XziXmn/legado-hub)
[![macOS](https://img.shields.io/badge/macOS-000000?logo=apple&logoColor=white)](https://github.com/XziXmn/legado-hub)
[![Web](https://img.shields.io/badge/Web-4285F4?logo=google-chrome&logoColor=white)](https://github.com/XziXmn/legado-hub)
[![Client](https://img.shields.io/badge/client-Reading%20%2F%20Legado-2563EB)](https://github.com/gedoor/legado)

</div>

管理员维护书源与官方账号，受邀用户用个人授权码搜索并订阅；服务端复用共享书库、检查更新并整理章节。Web 控制台只负责管理与订阅，**不替代阅读器**。

默认仅面向本机或受控局域网，不提供开放注册、匿名阅读、内置穿透或公网部署模式。

## 目录

- [主要功能](#主要功能)
- [使用流程](#使用流程)
- [快速部署](#快速部署)
  - [环境要求](#环境要求)
  - [Docker Compose](#docker-compose)
  - [可选配置](#可选配置)
  - [Docker CLI](#docker-cli)
  - [更新、停止与卸载](#更新停止与卸载)
- [完成首次配置](#完成首次配置)
- [接入 Reading / Legado](#接入-reading--legado)
- [数据目录与备份](#数据目录与备份)
- [常见问题](#常见问题)
- [网络与使用边界](#网络与使用边界)
- [开发者入口](#开发者入口)
- [贡献](#贡献)
- [许可证](#许可证)
- [English](#legadohub-english)

---

## 主要功能

| 能力 | 说明 |
| --- | --- |
| 书源治理 | 统一管理第三方书源、官方源登录状态与来源优先级 |
| 邀请制多用户 | 每位用户独立授权码与订阅设置；多人订同一本书时共享一份章节数据 |
| 后台整理 | 持续检查连载更新，支持暂停、恢复、归档与失败章节重试 |
| 阅读交付 | 向 Reading / Legado 提供聚合书架、目录、正文，以及来源支持的章节评论 |
| 入口分离 | `8765` 用户口 / Reading 书源；`8766` 管理口（请用防火墙限制访问来源） |

## 使用流程

```text
部署服务 → 管理员装插件 / 登录官方源 / 建用户
                ↓
用户用授权码进控制台 → 搜索并订阅
                ↓
Reading / Legado 导入聚合书源并登录同一授权码
                ↓
服务端持续更新共享章节 → 在阅读器中阅读
```

## 快速部署

推荐 **Docker Compose**。`8765` 是用户口 / Reading，`8766` 是管理口。

> 入口以 **root** 启动：按 `PUID`/`PGID` 修正挂载目录权限后，用 `gosu` 降权运行主进程。
> 把 `PUID`/`PGID` 设成 NAS 上共享文件夹的实际用户即可，一般不必再手搓 `chown`。
> `PUID` 与 `PGID` 必须是非零整数，主程序不会以 root 身份运行。

### 环境要求

| 项 | 说明 |
| --- | --- |
| 运行时 | Docker Engine；Compose 需 **v2**（`docker compose` 子命令） |
| 架构 | `linux/amd64`、`linux/arm64` 官方镜像 |
| 端口 | 宿主 `8765`（用户 / Reading）、`8766`（管理）空闲 |
| 磁盘 | 章节与缓存会持续增长，建议预留充足空间 |
| 网络 | 本机或受控局域网；请用防火墙限制 `8766` 的访问来源 |

### Docker Compose

#### 1. 准备目录

```bash
mkdir -p /opt/legado-hub && cd /opt/legado-hub
# 群晖示例: /volume1/docker/legado-hub
# 飞牛 / 绿联示例: /vol1/1000/appdata/legado-hub

mkdir -p data config generated runtime \
  plugins/sources/thirdparty plugins/sources/official
```

| 目录 | 内容 |
| --- | --- |
| `data/` | 数据库、书库、章节缓存、浏览器资料 |
| `config/` | 应用配置、插件 Cookie |
| `generated/` | 生成的聚合书源 |
| `runtime/` | 插件运行状态 |
| `plugins/sources/thirdparty/` | 第三方插件（空目录时由镜像种子填充） |
| `plugins/sources/official/` | 官方插件（需自行放入，只读挂载） |

权限策略（镜像内自动处理）：

| 路径 | 启动时行为 |
| --- | --- |
| `config` / `generated` / `runtime` / 第三方插件 | `chown -R` 到 `PUID:PGID` |
| `data` | 默认修正目录本身和 `app.db*`；不递归扫描整棵书库 |
| 官方插件（只读） | 不改权，只需宿主可读 |

更换过 `PUID`/`PGID` 或旧书库属主不对时，可一次性全量修权：

```bash
LEGADOHUB_CHOWN_DATA=1 docker compose up -d --force-recreate legadohub
docker compose up -d --force-recreate legadohub   # 恢复默认非递归
```

`docker compose restart` **不会**应用新的环境变量，不能用于这次迁移。

#### 2. 获取并编辑 compose 文件

```bash
curl -fsSL -o docker-compose.yml \
  https://raw.githubusercontent.com/XziXmn/legado-hub/main/docker-compose.yml
```

重点修改：

| 改什么 | 说明 |
| --- | --- |
| `PUID` / `PGID` | 与 NAS / 宿主实际用户一致（默认 `1000`） |
| `volumes` 左侧 | 宿主真实路径（NAS 请改成绝对路径，示例见 compose 内注释） |
| `ports` | 端口冲突时只改左侧宿主端口 |

结构示意：

```yaml
services:
  legadohub:
    image: xzixmn/legado-hub:latest
    ports:
      - '8765:8765'   # 用户入口 / Reading 书源
      - '8766:8766'   # 管理控制台（限制访问来源）
    environment:
      - TZ=Asia/Shanghai
      - PUID=1000
      - PGID=1000
    volumes:
      - './data:/app/backend/data'
      - './config:/app/backend/config'
      - './generated:/app/backend/generated'
      - './runtime:/app/backend/runtime'
      - './plugins/sources/thirdparty:/app/plugins/sources/thirdparty'
      - './plugins/sources/official:/app/plugins/sources/official:ro'
```

- **第三方插件**目录为空时，从镜像种子复制默认插件；之后以宿主目录为准，重启不会覆盖你的改动。
- **官方插件**不进镜像，放到宿主 `plugins/sources/official/<插件ID>/`（容器内只读）。

#### 3. 启动与健康检查

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f legadohub
```

首次拉取体积较大（含 Chromium），请耐心等待。约几十秒内应变为 `healthy`。

```bash
curl -s http://127.0.0.1:8765/api/auth/entrypoint   # "entrypoint":"public"
curl -s http://127.0.0.1:8766/api/auth/entrypoint   # "entrypoint":"admin"
```

| 现象 | 处理 |
| --- | --- |
| `runtime directory is not writable` | 核对 `PUID`/`PGID`；必要时用上文 `LEGADOHUB_CHOWN_DATA=1` |
| 一直 unhealthy | 看主服务日志；端口占用；是否已过 `start_period`（约 40s） |

#### 4. 取得管理员密码

空库首次启动创建 **`admin`**，随机密码**只打印一次**：

```bash
docker compose logs legadohub | grep -i password
```

Docker CLI 用户改用 `docker logs legadohub | grep -i password`。

错过日志时重置：

```bash
docker compose exec -T legadohub \
  python /app/backend/scripts/reset_user_password.py --username admin
```

Docker CLI 用户改用 `docker exec -i legadohub python /app/backend/scripts/reset_user_password.py --username admin`。

登录后请到 **设置 → 账户安全** 修改密码。

#### 5. 打开控制台

| 入口 | 地址（本机） | 用途 |
| --- | --- | --- |
| 管理控制台 | http://127.0.0.1:8766/ | 用户、书源、官方登录、设置 |
| 用户入口 | http://127.0.0.1:8765/ | 受邀用户搜索 / 订阅 |
| Reading 书源 | http://127.0.0.1:8765/api/subscribe/legado/source | 导入到 Reading / Legado |

局域网把 `127.0.0.1` 换成服务器 IP。**请用防火墙限制 `8766`**。

### 可选配置

| 文件 | 用途 |
| --- | --- |
| `docker-compose.plugins.yml` | 第三方插件改到自定义宿主目录（`LEGADOHUB_THIRDPARTY_PLUGINS_DIR`） |
| `docker-compose.browserless.yml` | 改用外部 Browserless（需 `LEGADOHUB_BROWSERLESS_TOKEN`） |

```bash
curl -fsSLO https://raw.githubusercontent.com/XziXmn/legado-hub/main/docker-compose.plugins.yml
export LEGADOHUB_THIRDPARTY_PLUGINS_DIR='/opt/legado-hub/plugins/sources/thirdparty'
docker compose -f docker-compose.yml -f docker-compose.plugins.yml up -d

curl -fsSLO https://raw.githubusercontent.com/XziXmn/legado-hub/main/docker-compose.browserless.yml
export LEGADOHUB_BROWSERLESS_TOKEN='请替换为随机密钥'
docker compose -f docker-compose.yml -f docker-compose.browserless.yml up -d
```

### Docker CLI

不使用 Compose 时：

```bash
mkdir -p data config generated runtime \
  plugins/sources/thirdparty plugins/sources/official
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

```bash
docker logs -f legadohub
```

### 更新、停止与卸载

Docker Compose：

```bash
# 更新
docker compose pull && docker compose up -d && docker compose ps

# 停止 / 删容器（保留宿主数据目录）
docker compose stop
docker compose down
```

Docker CLI 更新时，拉取镜像并删除旧容器，再重新执行上文 `docker run` 命令：

```bash
docker pull xzixmn/legado-hub:latest
docker stop legadohub
docker rm legadohub
```

CLI 仅停止或删除容器时，分别使用 `docker stop legadohub`、`docker rm legadohub`。绑定挂载的宿主数据目录不会随容器删除。

连数据一起删（不可恢复）前请确认路径，再删除宿主上的 `data`、`config`、`generated`、`runtime`、`plugins`。

## 完成首次配置

### 安装官方插件

镜像已附带第三方插件。官方插件需单独取得，按插件 ID 放入：

```text
plugins/sources/official/<插件 ID>/
  metadata.yaml
  source.py
  ...
```

```bash
docker compose restart legadohub
```

Docker CLI 用户改用 `docker restart legadohub`。

官方源可读范围取决于：插件能力、目标站状态、登录账号、账号自身权限。服务**不会**绕过站点付费与权限规则。

### 创建用户和订阅

1. 用 `admin` 登录管理口（`:8766`）。
2. 打开「用户管理」，创建普通用户。
3. **立刻保存**系统生成的个人授权码（对话框关闭后默认不再显示明文）。
4. 用户打开用户口（`:8765`），用授权码登录。
5. 搜索小说，选择起始章节创建订阅。
6. 在「我的书库」看到可读章节后，再到 Reading / Legado 阅读。

补充：

- 重置授权码会立即作废旧码与该用户已有会话。
- 删除普通用户会清理其会话、个人订阅和搜索任务，**不会**删除仍可供他人使用的共享书籍。
- 管理员使用用户名密码；普通读者使用个人授权码。

### 管理员侧建议检查

1. 书源 / 插件列表加载正常。
2. 需要的官方源已登录且状态有效。
3. 至少创建一名普通用户，并用其授权码走通：搜索 → 订阅。

## 接入 Reading / Legado

1. 在阅读器中添加网络书源 / 导入：

   ```text
   http://<服务器地址>:8765/api/subscribe/legado/source
   ```

2. 打开「LegadoHub 聚合」登录页，输入管理员发放的**个人授权码**。
3. 只有后端明确返回用户名时，才算登录成功。
4. 搜索结果包含：已入库并发布的共享书 + 当前启用的第三方书源结果。
5. **官方源只参与服务端聚合**，不会作为 Reading 直读源暴露。
6. 新增、暂停、恢复、归档订阅请在 Web 控制台完成；Reading 侧以阅读为主。

若改过宿主端口映射，书源 URL 中的端口要与映射后的用户口一致。

## 数据目录与备份

| 宿主目录 | 内容 | 是否可丢 |
| --- | --- | --- |
| `data` | 用户、订阅、共享书库、章节缓存、浏览器资料 | 否 |
| `config` | 应用配置、插件 Cookie | 否 |
| `generated` | 生成的聚合书源 | 可重建，建议仍备份 |
| `runtime` | 插件运行状态 | 可重建 |
| `plugins/sources/thirdparty` | 第三方插件 | 视你是否改过插件 |
| `plugins/sources/official` | 官方插件 | 否（镜像内没有） |

`config` 与完整备份可能含登录凭据，请勿公开上传或提交到 Git。

**备份步骤：**

1. 停止服务：Compose 使用 `docker compose stop`；Docker CLI 使用 `docker stop legadohub`
2. 完整打包 `data`、`config`、`generated`、`runtime`、`plugins`
3. 备份文件等同账号资产，离线加密保存
4. 恢复时解压回同一结构，再用 `docker compose up -d` 或 `docker start legadohub` 启动

## 常见问题

<details>
<summary><strong>为什么 Reading 中搜不到刚订阅的书？</strong></summary>

Reading 展示的是已发布共享书和启用的第三方书源结果。若要读服务端整理的聚合正文，请先在「我的书库」确认已有可读章节。

</details>

<details>
<summary><strong>为什么有的章节只有预览？</strong></summary>

服务不会绕过目标站付费规则。账号无完整正文权限、来源暂时失败，或补充来源尚未通过校验时，章节可能只有预览。

</details>

<details>
<summary><strong>为什么书源可达，正文仍然失败？</strong></summary>

可达只表示能连上目标站，不代表页面结构、登录状态或章节权限有效。以书籍详情里的失败信息为准。

</details>

<details>
<summary><strong>多个用户可以订阅同一本书吗？</strong></summary>

可以。系统只维护一份共享章节数据，每个用户各自保存订阅关系与设置。

</details>

<details>
<summary><strong>忘记管理员密码怎么办？</strong></summary>

```bash
docker compose exec -T legadohub \
  python /app/backend/scripts/reset_user_password.py --username admin
```

Docker CLI 用户改用 `docker exec -i legadohub python /app/backend/scripts/reset_user_password.py --username admin`。

会生成新密码并撤销该管理员现有会话。

</details>

<details>
<summary><strong>第三方插件目录被我清空了，会怎样？</strong></summary>

再次启动时若目录为空，入口会从镜像种子重新复制默认第三方插件；你本地的定制修改不会被恢复，除非你有备份。

</details>

<details>
<summary><strong>可以不用 Compose、只 docker run 吗？</strong></summary>

可以。见上文 [Docker CLI](#docker-cli)。

</details>

## 网络与使用边界

- 本项目不提供公网模式、内置穿透、反向代理或 TLS 配置。
- 自行建立外网访问时，域名、TLS、防火墙、可信代理、限流和管理员入口隔离由部署者负责。
- 仅在有权访问和处理相应内容的前提下使用，并遵守目标站服务条款、当地法律和版权要求。
- 本项目不是 Legado 官方项目，不保证第三方书源持续可用。

## 开发者入口

面向从源码开发或贡献插件的简要入口（详细约定见仓库文档）：

| 主题 | 位置 |
| --- | --- |
| 仓库布局与本地启动 | [`AGENTS.md`](AGENTS.md) |
| 书源插件合同 | [`docs/architecture/source-plugin-contract.md`](docs/architecture/source-plugin-contract.md) |
| 写插件技能 | [`docs/skills/book-source-craft/README.md`](docs/skills/book-source-craft/README.md) |
| 产品边界 | [`docs/PRODUCT.md`](docs/PRODUCT.md) |
| 全量校验 | 仓库根目录 `verify.ps1` |

本地开发概要（Windows）：

```powershell
# 或使用 .\start.bat
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
.venv/Scripts/python.exe -m playwright install chromium
Set-Location frontend
npm install
npm run build
Set-Location ../backend
../.venv/Scripts/python.exe -m app.server --host 0.0.0.0 --public-port 8765 --admin-port 8766
```

## 贡献

欢迎通过 [GitHub Issues](https://github.com/XziXmn/legado-hub/issues) 反馈问题与建议。

提交代码前请：

1. 阅读 [`AGENTS.md`](AGENTS.md) 与相关架构文档，确认改动落在正确边界内。
2. 保持单一职责：一个 PR 解决一个明确问题。
3. 运行 `verify.ps1`（或项目约定的等价校验），并在说明中写明结果。
4. 不要提交运行时数据：`data/`、`config/app_config.json`、Cookie、官方插件目录等。

书源插件请遵循插件合同；官方插件源不在本仓库镜像中分发。

## 许可证

本仓库当前**未附带** `LICENSE` 文件。在作者明确声明前，请勿默认按开源许可证再分发或商用。使用本软件时请遵守目标站点条款与当地法律。

问题反馈：[GitHub Issues](https://github.com/XziXmn/legado-hub/issues)

---

# LegadoHub (English)

**Self-hosted novel aggregation and subscription backend**

A source-plugin runtime and subscription service for [Reading](https://github.com/hectorqin/reader) / [Legado](https://github.com/gedoor/legado): operators maintain sources and accounts, the server processes chapters in the background, and day-to-day reading stays in the reader apps.

The web console is for management and subscriptions only; **it is not a replacement e-reader**.

Default deployment is local or trusted LAN only. There is no open registration, anonymous reading, built-in tunnel, or public cloud mode.

### Table of Contents

- [Features](#features)
- [Workflow](#workflow)
- [Quick Deploy](#quick-deploy)
  - [Requirements](#requirements)
  - [Docker Compose](#docker-compose-1)
  - [Optional overrides](#optional-overrides)
  - [Docker CLI](#docker-cli-1)
  - [Update, stop, and remove](#update-stop-and-remove)
- [First-time setup](#first-time-setup)
- [Connect Reading / Legado](#connect-reading--legado)
- [Data directories and backup](#data-directories-and-backup)
- [FAQ](#faq)
- [Network and usage boundaries](#network-and-usage-boundaries)
- [Developer entry points](#developer-entry-points)
- [Contributing](#contributing)
- [License](#license)

### Features

| Capability | Description |
| --- | --- |
| Source governance | Manage third-party plugins, official-source login state, and source priority |
| Invitation-only multi-user | Each reader gets a personal auth code; many users share one processed chapter library per book |
| Background processing | Track serial updates; pause, resume, archive, and retry failed chapters |
| Reading delivery | Expose aggregate shelf, TOC, chapter body, and supported chapter reviews to Reading / Legado |
| Split entrypoints | `8765` reader / Reading source; `8766` admin console (firewall-restrict this port) |

### Workflow

```text
Deploy → admin installs plugins / logs into official sources / creates users
                ↓
Reader opens console with auth code → search & subscribe
                ↓
Import aggregate source in Reading / Legado and log in with the same code
                ↓
Server keeps shared chapters updated → read in the reader app
```

### Quick Deploy

**Docker Compose** is recommended. Port `8765` is the reader entry; `8766` is admin.

> The entrypoint starts as **root**, repairs mount ownership for `PUID`/`PGID`, then drops privileges with `gosu`.
> Set `PUID`/`PGID` to the real owner of your NAS share so you usually do not need manual `chown`.
> Both must be non-zero integers; the app process does not run as root.

#### Requirements

| Item | Notes |
| --- | --- |
| Runtime | Docker Engine; Compose **v2** (`docker compose`) |
| Arch | Official images for `linux/amd64` and `linux/arm64` |
| Ports | Host `8765` (reader / Reading) and `8766` (admin) free |
| Disk | Chapter caches grow over time; reserve enough space |
| Network | Localhost or controlled LAN; restrict access to `8766` |

#### Docker Compose

##### 1. Prepare directories

```bash
mkdir -p /opt/legado-hub && cd /opt/legado-hub
# Synology example: /volume1/docker/legado-hub
# Other NAS examples: /vol1/1000/appdata/legado-hub

mkdir -p data config generated runtime \
  plugins/sources/thirdparty plugins/sources/official
```

| Directory | Contents |
| --- | --- |
| `data/` | Database, library, chapter cache, browser profiles |
| `config/` | App config, plugin cookies |
| `generated/` | Generated aggregate book source |
| `runtime/` | Plugin runtime state |
| `plugins/sources/thirdparty/` | Third-party plugins (seeded from the image when empty) |
| `plugins/sources/official/` | Official plugins (operator-provided, read-only mount) |

Ownership policy (handled by the image entrypoint):

| Path | On startup |
| --- | --- |
| `config` / `generated` / `runtime` / third-party plugins | Recursive `chown` to `PUID:PGID` |
| `data` | Fixes the mount root and `app.db*` by default; does not recurse the whole library |
| Official plugins (read-only) | Ownership unchanged; host path must be readable |

One-shot full data chown after changing `PUID`/`PGID` or fixing legacy trees:

```bash
LEGADOHUB_CHOWN_DATA=1 docker compose up -d --force-recreate legadohub
docker compose up -d --force-recreate legadohub   # restore default non-recursive mode
```

`docker compose restart` does **not** apply new environment variables.

##### 2. Fetch and edit compose

```bash
curl -fsSL -o docker-compose.yml \
  https://raw.githubusercontent.com/XziXmn/legado-hub/main/docker-compose.yml
```

| Field | What to change |
| --- | --- |
| `PUID` / `PGID` | Match the real host/NAS user (default `1000`) |
| `volumes` left side | Real host paths (use absolute paths on NAS; see comments in the file) |
| `ports` | Change only the host side if ports conflict |

Skeleton:

```yaml
services:
  legadohub:
    image: xzixmn/legado-hub:latest
    ports:
      - '8765:8765'   # reader / Reading source
      - '8766:8766'   # admin console (restrict access)
    environment:
      - TZ=Asia/Shanghai
      - PUID=1000
      - PGID=1000
    volumes:
      - './data:/app/backend/data'
      - './config:/app/backend/config'
      - './generated:/app/backend/generated'
      - './runtime:/app/backend/runtime'
      - './plugins/sources/thirdparty:/app/plugins/sources/thirdparty'
      - './plugins/sources/official:/app/plugins/sources/official:ro'
```

- **Third-party plugins**: seeded once when the host directory is empty; later restarts never overwrite host files.
- **Official plugins**: not in the image; place under `plugins/sources/official/<plugin_id>/` (read-only in the container).

##### 3. Start and health-check

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f legadohub
```

First pull is large (includes Chromium). The service should become `healthy` within tens of seconds.

```bash
curl -s http://127.0.0.1:8765/api/auth/entrypoint   # "entrypoint":"public"
curl -s http://127.0.0.1:8766/api/auth/entrypoint   # "entrypoint":"admin"
```

| Symptom | Action |
| --- | --- |
| `runtime directory is not writable` | Check `PUID`/`PGID`; use `LEGADOHUB_CHOWN_DATA=1` if needed |
| Stays unhealthy | Inspect logs; port conflicts; wait past `start_period` (~40s) |

##### 4. Admin password

On first empty DB boot, user **`admin`** is created and a high-entropy password is printed **once**:

```bash
docker compose logs legadohub | grep -i password
```

Docker CLI users can run `docker logs legadohub | grep -i password` instead.

Reset if you missed the log line:

```bash
docker compose exec -T legadohub \
  python /app/backend/scripts/reset_user_password.py --username admin
```

Docker CLI users can run `docker exec -i legadohub python /app/backend/scripts/reset_user_password.py --username admin` instead.

Change the password under **Settings → Account security** after login.

##### 5. Open the consoles

| Entry | URL (localhost) | Purpose |
| --- | --- | --- |
| Admin console | http://127.0.0.1:8766/ | Users, sources, official login, settings |
| Reader entry | http://127.0.0.1:8765/ | Invited search / subscribe |
| Reading source | http://127.0.0.1:8765/api/subscribe/legado/source | Import into Reading / Legado |

On LAN, replace `127.0.0.1` with the server IP. **Firewall-restrict port `8766`.**

#### Optional overrides

| File | Purpose |
| --- | --- |
| `docker-compose.plugins.yml` | Custom host path for third-party plugins (`LEGADOHUB_THIRDPARTY_PLUGINS_DIR`) |
| `docker-compose.browserless.yml` | External Browserless (`LEGADOHUB_BROWSERLESS_TOKEN`) |

```bash
curl -fsSLO https://raw.githubusercontent.com/XziXmn/legado-hub/main/docker-compose.plugins.yml
export LEGADOHUB_THIRDPARTY_PLUGINS_DIR='/opt/legado-hub/plugins/sources/thirdparty'
docker compose -f docker-compose.yml -f docker-compose.plugins.yml up -d

curl -fsSLO https://raw.githubusercontent.com/XziXmn/legado-hub/main/docker-compose.browserless.yml
export LEGADOHUB_BROWSERLESS_TOKEN='replace-with-a-random-secret'
docker compose -f docker-compose.yml -f docker-compose.browserless.yml up -d
```

#### Docker CLI

Without Compose:

```bash
mkdir -p data config generated runtime \
  plugins/sources/thirdparty plugins/sources/official
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

```bash
docker logs -f legadohub
```

#### Update, stop, and remove

Docker Compose:

```bash
# Update
docker compose pull && docker compose up -d && docker compose ps

# Stop / remove container (host data directories kept)
docker compose stop
docker compose down
```

For Docker CLI updates, pull the image, remove the old container, then rerun the `docker run` command above:

```bash
docker pull xzixmn/legado-hub:latest
docker stop legadohub
docker rm legadohub
```

To only stop or remove the CLI container, use `docker stop legadohub` or `docker rm legadohub`. Bind-mounted host data is not removed with the container.

To delete data as well (irreversible), confirm paths first, then remove host `data`, `config`, `generated`, `runtime`, and `plugins`.

### First-time setup

#### Official plugins

Third-party plugins ship with the image. Official plugins must be obtained separately and placed by plugin ID:

```text
plugins/sources/official/<plugin_id>/
  metadata.yaml
  source.py
  ...
```

```bash
docker compose restart legadohub
```

Docker CLI users can run `docker restart legadohub` instead.

Readable official content depends on plugin capability, site status, login, and account entitlements. The service **does not** bypass paid or permission rules.

#### Create users and subscriptions

1. Log in as `admin` on the admin port (`:8766`).
2. Open **User management** and create a regular user.
3. **Save the personal auth code immediately** (plaintext is not shown again by default after the dialog closes).
4. The reader opens the reader port (`:8765`) and logs in with that code.
5. Search for a novel and subscribe from a chosen start chapter.
6. Once readable chapters appear under **My library**, continue in Reading / Legado.

Notes:

- Resetting an auth code invalidates the old code and that user’s sessions immediately.
- Deleting a regular user clears their sessions, personal subscriptions, and search jobs; it does **not** delete shared books still used by others.
- Admins use username/password; readers use personal auth codes.

#### Operator checklist

1. Plugin / source list loads.
2. Required official sources are logged in and valid.
3. At least one regular user can complete: search → subscribe.

### Connect Reading / Legado

1. Add / import the network source in the reader:

   ```text
   http://<server-host>:8765/api/subscribe/legado/source
   ```

2. Open the **LegadoHub aggregate** login page and enter the personal auth code issued by the admin.
3. Login succeeds only when the backend returns a username explicitly.
4. Search results include published shared books plus enabled third-party sources.
5. **Official sources participate only in server-side aggregation**; they are not exposed as direct Reading sources.
6. Create, pause, resume, and archive subscriptions in the web console; use Reading primarily for reading.

If you remapped host ports, the source URL port must match the reader entry mapping.

### Data directories and backup

| Host path | Contents | Disposable? |
| --- | --- | --- |
| `data` | Users, subscriptions, shared library, chapter cache, browser profiles | No |
| `config` | App config, plugin cookies | No |
| `generated` | Generated aggregate source | Rebuildable; still recommend backup |
| `runtime` | Plugin runtime state | Rebuildable |
| `plugins/sources/thirdparty` | Third-party plugins | Depends on local edits |
| `plugins/sources/official` | Official plugins | No (not in the image) |

`config` and full backups may contain credentials; do not upload them publicly or commit them to Git.

**Backup:**

1. Stop the service with `docker compose stop` or `docker stop legadohub`
2. Archive `data`, `config`, `generated`, `runtime`, and `plugins`
3. Treat backups as account secrets; store encrypted offline
4. Restore to the same layout, then start with `docker compose up -d` or `docker start legadohub`

### FAQ

<details>
<summary><strong>Why doesn’t a just-subscribed book show up in Reading search?</strong></summary>

Reading shows published shared books and enabled third-party sources. For server-processed aggregate text, wait until **My library** has readable chapters.

</details>

<details>
<summary><strong>Why are some chapters preview-only?</strong></summary>

The service does not bypass site paywalls. Missing account rights, temporary source failures, or unvalidated fallback sources can leave a chapter as preview only.

</details>

<details>
<summary><strong>The source is reachable but chapter body still fails?</strong></summary>

Reachability only means the site responds, not that page structure, login, or chapter rights are valid. Trust the failure details on the book page.

</details>

<details>
<summary><strong>Can multiple users subscribe to the same book?</strong></summary>

Yes. There is one shared chapter corpus per book; each user keeps their own subscription and settings.

</details>

<details>
<summary><strong>Forgot the admin password?</strong></summary>

```bash
docker compose exec -T legadohub \
  python /app/backend/scripts/reset_user_password.py --username admin
```

Docker CLI users can run `docker exec -i legadohub python /app/backend/scripts/reset_user_password.py --username admin` instead.

This prints a new password and revokes existing admin sessions.

</details>

<details>
<summary><strong>What if I emptied the third-party plugins directory?</strong></summary>

On the next start, if the directory is empty, the entrypoint reseeds default third-party plugins from the image. Local customizations are not restored without a backup.

</details>

<details>
<summary><strong>Can I run with only `docker run`?</strong></summary>

Yes; see [Docker CLI](#docker-cli-1).

</details>

### Network and usage boundaries

- No built-in public mode, tunnel, reverse proxy, or TLS setup is provided.
- If you expose the service externally, DNS, TLS, firewall, trusted proxies, rate limits, and admin isolation are operator-owned.
- Use only content you are allowed to access and process; follow site terms, local law, and copyright rules.
- This is not an official Legado project and does not guarantee third-party sources stay available.

### Developer entry points

Brief pointers for source development and plugins:

| Topic | Location |
| --- | --- |
| Repo layout and local run | [`AGENTS.md`](AGENTS.md) |
| Source plugin contract | [`docs/architecture/source-plugin-contract.md`](docs/architecture/source-plugin-contract.md) |
| Plugin authoring skill | [`docs/skills/book-source-craft/README.md`](docs/skills/book-source-craft/README.md) |
| Product boundaries | [`docs/PRODUCT.md`](docs/PRODUCT.md) |
| Full verification | Root `verify.ps1` |

Local development sketch (Windows):

```powershell
# or use .\start.bat
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
.venv/Scripts/python.exe -m playwright install chromium
Set-Location frontend
npm install
npm run build
Set-Location ../backend
../.venv/Scripts/python.exe -m app.server --host 0.0.0.0 --public-port 8765 --admin-port 8766
```

### Contributing

Feedback and bug reports are welcome via [GitHub Issues](https://github.com/XziXmn/legado-hub/issues).

Before sending a PR:

1. Read [`AGENTS.md`](AGENTS.md) and the relevant architecture docs so the change lands in the right boundary.
2. Keep a single clear problem per PR.
3. Run `verify.ps1` (or the documented equivalent) and report results.
4. Do not commit runtime data: `data/`, `config/app_config.json`, cookies, official plugin trees, etc.

Follow the plugin contract for source plugins. Official plugin sources are not redistributed inside the published image.

### License

This repository currently **does not ship** a `LICENSE` file. Do not assume an open-source license for redistribution or commercial use until the author states one. Use of the software remains subject to target-site terms and applicable law.

Issues: [GitHub Issues](https://github.com/XziXmn/legado-hub/issues)
