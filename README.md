<div align="center">

# LegadoHub

**自托管小说聚合订阅服务**

面向 [Reading](https://github.com/hectorqin/reader) / [Legado](https://github.com/gedoor/legado) 的书源与订阅后端：
统一维护书源与账号，后台整理章节，日常阅读仍在 Reading / Legado 完成。

[![Docker Image](https://img.shields.io/badge/Docker-xzixmn%2Flegado--hub-2496ED?style=flat-square&logo=docker&logoColor=white)](https://hub.docker.com/r/xzixmn/legado-hub)
![Platform](https://img.shields.io/badge/platform-amd64%20%7C%20arm64-475569?style=flat-square)
![Client](https://img.shields.io/badge/client-Reading%20%2F%20Legado-2563EB?style=flat-square)

</div>

---

管理员维护书源与官方账号，受邀用户用个人授权码搜索并订阅；服务端复用共享书库、检查更新并整理章节。Web 控制台只负责管理与订阅，**不替代阅读器**。

默认仅面向本机或受控局域网，不提供开放注册、匿名阅读、内置穿透或公网部署模式。

## 目录

- [主要功能](#主要功能)
- [使用流程](#使用流程)
- [部署](#部署)
  - [环境要求](#环境要求)
  - [1. 准备目录](#1-准备目录)
  - [2. 获取并编辑 docker-compose.yml](#2-获取并编辑-docker-composeyml)
  - [3. 启动服务](#3-启动服务)
  - [4. 确认健康状态](#4-确认健康状态)
  - [5. 取得管理员密码](#5-取得管理员密码)
  - [6. 打开控制台](#6-打开控制台)
  - [可选配置](#可选配置)
  - [Docker CLI](#docker-cli)
  - [更新、停止与卸载](#更新停止与卸载)
- [完成首次配置](#完成首次配置)
- [接入 Reading / Legado](#接入-readinglegado)
- [数据目录](#数据目录)
- [备份](#备份)
- [常见问题](#常见问题)
- [网络与使用边界](#网络与使用边界)

## 主要功能

| 能力 | 说明 |
| --- | --- |
| 书源治理 | 统一管理第三方书源、官方源登录状态与来源优先级 |
| 邀请制多用户 | 每位用户独立授权码与订阅设置；多人订同一本书时共享一份章节数据 |
| 后台整理 | 持续检查连载更新，支持暂停、恢复、归档与失败章节重试 |
| 阅读交付 | 向 Reading / Legado 提供聚合书架、目录、正文，以及来源支持的章节评论 |
| 入口分离 | 管理口与用户口分端口；管理员可创建、禁用、删除普通用户 |

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

## 部署

推荐 **Docker Compose**。同时提供完整的 Docker CLI 命令，适合不使用 Compose 的环境。`8765` 是用户口 / Reading，`8766` 是管理口。

> 入口以 **root** 启动：按 `PUID`/`PGID` 修正挂载目录权限后，用 `gosu` 降权运行主进程（与 CloudGather 等 NAS 应用习惯一致）。
> 把 `PUID`/`PGID` 设成 NAS 上共享文件夹的实际用户即可，一般**不必**再手搓 `chown`。
> `PUID` 与 `PGID` 必须是非零整数，主程序不会以 root 身份运行。

### 环境要求

| 项 | 说明 |
| --- | --- |
| 运行时 | Docker Engine；Compose 需 **v2**（`docker compose` 子命令） |
| 架构 | `linux/amd64`、`linux/arm64` 官方镜像 |
| 端口 | 宿主 `8765`（用户 / Reading）、`8766`（管理）空闲 |
| 磁盘 | 章节与缓存会持续增长，建议预留充足空间 |
| 网络 | 本机或受控局域网；请用防火墙限制 `8766` 的访问来源 |

### 1. 准备目录

在 NAS 或 Linux 上建一个长期保留的数据目录，例如：

```bash
# 普通 Linux 示例
mkdir -p /opt/legado-hub
cd /opt/legado-hub

# 飞牛 / 绿联等常见写法示例
# mkdir -p /vol1/1000/appdata/legado-hub
# cd /vol1/1000/appdata/legado-hub

# 群晖示例
# mkdir -p /volume1/docker/legado-hub
# cd /volume1/docker/legado-hub
```

可选：预先建好子目录（不建也行，入口会 `mkdir` 并按 `PUID`/`PGID` 改权）：

```bash
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
| `data` | 默认修正目录本身和 `app.db*`，并检查顶层目录；不扫描整棵书库 |
| 官方插件（只读） | 不改权，只需宿主可读 |

若更换过 `PUID`/`PGID`，入口会自动修复 SQLite 文件。旧书库整树属主不对时，用一次性重建完成全量修权：

```bash
LEGADOHUB_CHOWN_DATA=1 docker compose up -d --force-recreate legadohub
docker compose up -d --force-recreate legadohub
```

第二条命令会恢复默认的非递归启动。`docker compose restart` 不会应用新的环境变量，不能用于这次迁移。

### 2. 获取并编辑 docker-compose.yml

```bash
curl -fsSL -o docker-compose.yml \
  https://raw.githubusercontent.com/XziXmn/legado-hub/main/docker-compose.yml
```

也可用仓库根目录现成文件。下载后**按自己的机器改**，重点：

| 改什么 | 说明 |
| --- | --- |
| `PUID` / `PGID` | 与 NAS/宿主实际用户一致（默认 `1000`） |
| `volumes` 左侧 | 宿主真实路径 |
| `ports` | 端口冲突时改左侧宿主端口 |
| `LEGADOHUB_EXTERNAL_HOST` | 可选，固定 IP / 域名（不要带 `http://` 和端口） |

结构示意（完整注释版以仓库文件为准）：

```yaml
services:
  # LegadoHub | 小说聚合订阅
  legadohub:
    image: xzixmn/legado-hub:latest
    container_name: legadohub
    restart: always
    init: true
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - DAC_OVERRIDE
      - SETGID
      - SETUID
    ports:
      - '8765:8765' # 用户入口 / Reading 书源
      - '8766:8766' # 管理控制台（限制访问来源）
    environment:
      - TZ=Asia/Shanghai
      - PUID=1000 # 改成 NAS 实际用户
      - PGID=1000 # 改成 NAS 实际用户组
      - LEGADOHUB_CHOWN_DATA=${LEGADOHUB_CHOWN_DATA:-0}
      - LEGADOHUB_EXTERNAL_HOST=${LEGADOHUB_EXTERNAL_HOST:-}
    volumes:
      - './data:/app/backend/data'
      - './config:/app/backend/config'
      - './generated:/app/backend/generated'
      - './runtime:/app/backend/runtime'
      - './plugins/sources/thirdparty:/app/plugins/sources/thirdparty'
      - './plugins/sources/official:/app/plugins/sources/official:ro'
      # NAS 绝对路径示例见仓库 docker-compose.yml 内注释
    logging:
      driver: json-file
      options:
        max-size: '10m'
        max-file: '3'
    networks:
      - legadohub_internal
    healthcheck:
      test: ['CMD', 'python', '-c', '...'] # 探测 8765 + 8766
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 40s

networks:
  legadohub_internal:
    driver: bridge
```

**NAS 挂载示例**（把上面 `./data` 等整组替换为绝对路径）：

```yaml
# 飞牛 / 绿联
- '/vol1/1000/appdata/legado-hub/data:/app/backend/data'
- '/vol1/1000/appdata/legado-hub/config:/app/backend/config'
- '/vol1/1000/appdata/legado-hub/generated:/app/backend/generated'
- '/vol1/1000/appdata/legado-hub/runtime:/app/backend/runtime'
- '/vol1/1000/appdata/legado-hub/plugins/thirdparty:/app/plugins/sources/thirdparty'
- '/vol1/1000/appdata/legado-hub/plugins/official:/app/plugins/sources/official:ro'

# 群晖
# - '/volume1/docker/legado-hub/data:/app/backend/data'
# ...

# 普通 Linux
# - '/opt/legado-hub/data:/app/backend/data'
# ...
```

补充：

- **第三方插件**目录为空时，会从镜像种子复制默认插件；之后以宿主目录为准，不会在重启时覆盖你的改动。
- **官方插件**不进镜像，放到宿主 `.../plugins/official/<插件ID>/`（容器内只读）。
### 3. 启动服务

```bash
docker compose pull
docker compose up -d
```

首次拉取 `xzixmn/legado-hub:latest` 体积较大（含 Chromium），请耐心等待。

端口冲突时，只改映射左侧，例如 `'8875:8765'`，浏览器和 Reading 书源 URL 也要用新端口。

### 4. 确认健康状态

```bash
docker compose ps
docker compose logs -f legadohub
```

| 检查项 | 正常表现 |
| --- | --- |
| `legadohub` | `running`，健康检查 `healthy`（约几十秒内） |
| 日志 | 出现监听与首次管理员创建信息 |

本机探测：

```bash
curl -s http://127.0.0.1:8765/api/auth/entrypoint   # "entrypoint":"public"
curl -s http://127.0.0.1:8766/api/auth/entrypoint   # "entrypoint":"admin"
```

| 现象 | 处理 |
| --- | --- |
| `runtime directory is not writable` | 核对 `PUID`/`PGID`；需要全量修权时按上文用 `LEGADOHUB_CHOWN_DATA=1 docker compose up -d --force-recreate` |
| 一直 unhealthy | 看主服务日志；端口是否占用；是否已过 `start_period`（约 40s） |
| 旧书库文件无法写入 | `data` 默认不递归 chown；按上文执行一次性全量修权，不能只用 `restart` |

### 5. 取得管理员密码

空库首次启动创建 **`admin`**，随机密码**只打印一次**：

```bash
docker compose logs legadohub | grep -i password
```

错过日志时重置：

```bash
docker compose exec -T legadohub \
  python /app/backend/scripts/reset_user_password.py --username admin
```

登录后请到 **设置 → 账户安全** 修改密码。

### 6. 打开控制台

| 入口 | 地址（本机） | 用途 |
| --- | --- | --- |
| 管理控制台 | http://127.0.0.1:8766/console | 用户、书源、官方登录、设置 |
| 用户入口 | http://127.0.0.1:8765/login | 受邀用户搜索 / 订阅 |
| Reading 书源 | http://127.0.0.1:8765/api/subscribe/legado/source | 导入到 Reading / Legado |

局域网把 `127.0.0.1` 换成 NAS/服务器 IP，例如 `http://192.168.1.20:8766/console`。
**请用防火墙限制 `8766`**，不要把管理口暴露到不受信网络。

### 可选配置

#### 固定访问主机名

在 compose 的 `environment` 里写死，或用同目录 `.env`：

```env
LEGADOHUB_EXTERNAL_HOST=192.168.1.20
```

```bash
docker compose up -d
```

只填主机名或 IP，不要带协议、端口、路径。该变量只影响允许的 Host / 生成链接，**不会**配置防火墙、TLS 或穿透。

#### 其它 override（可选）

仓库另附：

- `docker-compose.plugins.yml`：第三方插件改到自定义宿主目录（`LEGADOHUB_THIRDPARTY_PLUGINS_DIR`）
- `docker-compose.browserless.yml`：改用外部 Browserless（需 `LEGADOHUB_BROWSERLESS_TOKEN`）

```bash
docker compose -f docker-compose.yml -f docker-compose.plugins.yml up -d
```

Browserless 模式：

```bash
export LEGADOHUB_BROWSERLESS_TOKEN='请替换为随机密钥'
docker compose -f docker-compose.yml -f docker-compose.browserless.yml up -d
```

两个服务都在 `legadohub_internal` bridge 网络中，`ws://browserless:3000` 可直接解析。

### Docker CLI

不使用 Compose 时，先准备目录并拉取镜像：

```bash
mkdir -p data config generated runtime \
  plugins/sources/thirdparty plugins/sources/official
docker pull xzixmn/legado-hub:latest
```

启动：

```bash
docker run -d \
  --name legadohub \
  --restart always \
  --init \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  --cap-add CHOWN \
  --cap-add DAC_OVERRIDE \
  --cap-add SETGID \
  --cap-add SETUID \
  -p 8765:8765 \
  -p 8766:8766 \
  -e TZ=Asia/Shanghai \
  -e PUID=1000 \
  -e PGID=1000 \
  -e LEGADOHUB_CHOWN_DATA=0 \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  -v "$PWD/data:/app/backend/data" \
  -v "$PWD/config:/app/backend/config" \
  -v "$PWD/generated:/app/backend/generated" \
  -v "$PWD/runtime:/app/backend/runtime" \
  -v "$PWD/plugins/sources/thirdparty:/app/plugins/sources/thirdparty" \
  -v "$PWD/plugins/sources/official:/app/plugins/sources/official:ro" \
  xzixmn/legado-hub:latest
```

查看启动状态和首次管理员密码：

```bash
docker ps --filter name=legadohub
docker logs -f legadohub
```

更新时拉取镜像、删除旧容器，再使用上面的 `docker run` 命令重建。挂载目录中的数据不会随容器删除。

### 更新、停止与卸载

```bash
# 更新
docker compose pull
docker compose up -d
docker compose ps

# 停止 / 删容器（保留数据卷对应的宿主目录）
docker compose stop
docker compose down
```

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

放置后重启：

```bash
docker compose restart legadohub
```

官方源可读范围取决于：插件能力、目标站状态、登录账号、账号自身权限。服务**不会**绕过站点付费与权限规则。

### 创建用户和订阅

1. 用 `admin` 登录 http://服务器:8766/console 。
2. 打开「用户管理」，创建普通用户。
3. **立刻保存**系统生成的个人授权码（对话框关闭后默认不再显示明文）。
4. 用户打开 http://服务器:8765/login ，用授权码登录。
5. 搜索小说，选择起始章节创建订阅。
6. 在「我的书库」看到可读章节后，再到 Reading / Legado 阅读。

补充：

- 重置授权码会立即作废旧码与该用户已有会话。
- 删除普通用户会清理其会话、个人订阅和搜索任务，**不会**删除仍可供他人使用的共享书籍。
- 管理员账号使用用户名密码；普通读者使用个人授权码。

### 管理员侧建议检查

首次可用前，建议在管理控制台确认：

1. 书源 / 插件列表加载正常。
2. 需要的官方源已登录且状态有效。
3. 至少创建一名普通用户，并用其授权码在用户入口走通一次搜索 → 订阅。

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

## 数据目录

| 宿主目录 | 内容 | 是否可丢 |
| --- | --- | --- |
| `data` | 用户、订阅、共享书库、章节缓存、浏览器资料 | 否 |
| `config` | 应用配置、插件 Cookie | 否 |
| `generated` | 生成的聚合书源 | 可重建，建议仍备份 |
| `runtime` | 插件运行状态 | 可重建 |
| `plugins/sources/thirdparty` | 第三方插件 | 视你是否改过插件 |
| `plugins/sources/official` | 官方插件 | 否（镜像内没有） |

`config` 与完整备份可能含登录凭据，请勿公开上传或提交到 Git。

## 备份

1. 先停止写入：`docker compose stop`
2. 完整打包工作目录中的 `data`、`config`、`generated`、`runtime`、`plugins`
3. 备份文件等同账号资产，离线加密保存
4. 恢复时解压回同一结构，再 `docker compose up -d`（入口会按 `PUID`/`PGID` 校正挂载权限）

## 常见问题

<details>
<summary><strong>为什么 Reading 中搜不到刚订阅的书？</strong></summary>

Reading 展示的是已发布共享书和启用的第三方书源结果。若要读服务端整理的聚合正文，请先在「我的书库」确认已有可读章节；第三方结果还取决于目标站当时是否可访问。

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

会生成新密码并撤销该管理员现有会话。

</details>

<details>
<summary><strong>第三方插件目录被我清空了，会怎样？</strong></summary>

再次启动时，若目录为空，入口脚本会从镜像种子重新复制默认第三方插件；你本地的定制修改不会被恢复，除非你有备份。

</details>

<details>
<summary><strong>可以不用 Compose、只 docker run 吗？</strong></summary>

可以。上面的 [Docker CLI](#docker-cli) 已给出完整命令；入口会修权后降权运行。

</details>

## 网络与使用边界

- 本项目不提供公网模式、内置穿透、反向代理或 TLS 配置。
- 自行建立外网访问时，域名、TLS、防火墙、可信代理、限流和管理员入口隔离由部署者负责。
- 仅在有权访问和处理相应内容的前提下使用，并遵守目标站服务条款、当地法律和版权要求。
- 本项目不是 Legado 官方项目，不保证第三方书源持续可用。

---

问题反馈：[GitHub Issues](https://github.com/XziXmn/legado-hub/issues)
