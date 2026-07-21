<div align="center">
  <h1>小说聚合订阅</h1>
  <p><strong>LegadoHub</strong></p>
  <p>集中维护书源与小说订阅，持续整理章节，最终回到 Reading/Legado 阅读。</p>
  <p>
    <a href="https://hub.docker.com/r/xzixmn/legado-hub"><img alt="Docker Image" src="https://img.shields.io/badge/Docker-xzixmn%2Flegado--hub-2496ED?style=flat-square&amp;logo=docker&amp;logoColor=white"></a>
    <img alt="Platform" src="https://img.shields.io/badge/platform-amd64%20%7C%20arm64-475569?style=flat-square">
    <img alt="Client" src="https://img.shields.io/badge/client-Reading%20%2F%20Legado-2563EB?style=flat-square">
  </p>
</div>

小说聚合订阅是一套面向 Reading/Legado 的自托管订阅服务。管理员统一维护书源和官方账号，受邀用户使用个人授权码搜索并订阅小说；服务端复用共享书库、检查更新并整理章节，Web 控制台只负责管理和订阅，日常阅读仍在 Reading/Legado 中完成。

项目默认服务于本机或受控局域网，不提供开放注册、匿名阅读、内置穿透或公网部署模式。

## 主要功能

- 统一管理第三方书源、官方源登录状态和来源优先级。
- 每位用户使用独立授权码和订阅设置，多人订阅同一本书时共享一份章节数据。
- 后台持续检查连载更新，支持暂停、恢复、归档和失败章节重试。
- 向 Reading/Legado 提供聚合书架、目录、正文及来源支持的章节评论。
- 管理入口与用户入口分离，管理员可以创建、禁用和删除普通用户。

## 使用流程

1. 管理员部署服务并从启动日志取得首次登录密码。
2. 管理员安装所需官方插件、完成官方源登录并创建普通用户。
3. 用户使用个人授权码进入 Web 控制台，搜索小说并建立订阅。
4. Reading/Legado 导入聚合书源并使用同一授权码登录。
5. 服务端持续更新共享章节，用户在 Reading/Legado 中阅读。

## 快速部署

需要 Docker Engine。Docker Compose 方式还需要 Compose v2。官方镜像支持 `linux/amd64` 和 `linux/arm64`，默认不需要 `.env` 文件。

### Docker Compose 部署（推荐）

```bash
mkdir -p legado-hub
cd legado-hub
curl -fsSL -o docker-compose.yml \
  https://raw.githubusercontent.com/XziXmn/legado-hub/main/docker-compose.yml
docker compose pull
docker compose up -d
docker compose ps
```

Compose 会自动创建并初始化持久化目录。服务显示为 `healthy` 后查看首次启动日志：

```bash
docker compose logs legadohub
```

### Docker 部署

以下命令适用于 Linux 和常见 NAS 的 Shell。先创建宿主目录并用一次性容器初始化权限：

```bash
mkdir -p legado-hub
cd legado-hub
mkdir -p data config generated runtime plugins/sources/thirdparty plugins/sources/official
docker pull xzixmn/legado-hub:latest

docker run --rm \
  --user 0:0 \
  --network none \
  --read-only \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  --cap-add CHOWN \
  --cap-add DAC_OVERRIDE \
  -v "$PWD/data:/app/backend/data" \
  -v "$PWD/config:/app/backend/config" \
  -v "$PWD/generated:/app/backend/generated" \
  -v "$PWD/runtime:/app/backend/runtime" \
  -v "$PWD/plugins/sources/thirdparty:/app/plugins/sources/thirdparty" \
  xzixmn/legado-hub:latest \
  --initialize-runtime /app/plugins/sources/thirdparty
```

然后启动主服务：

```bash
docker run -d \
  --name legadohub \
  --restart unless-stopped \
  --init \
  -p 8765:8765 \
  -p 8766:8766 \
  -v "$PWD/data:/app/backend/data" \
  -v "$PWD/config:/app/backend/config" \
  -v "$PWD/generated:/app/backend/generated" \
  -v "$PWD/runtime:/app/backend/runtime" \
  -v "$PWD/plugins/sources/thirdparty:/app/plugins/sources/thirdparty" \
  -v "$PWD/plugins/sources/official:/app/plugins/sources/official:ro" \
  --tmpfs /tmp:rw,size=512m,mode=1777 \
  --tmpfs /home/legadohub/.cache:rw,size=256m,mode=700,uid=1000,gid=1000 \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  --pids-limit 256 \
  --memory 2g \
  --cpus 2 \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  xzixmn/legado-hub:latest

docker logs legadohub
```

空数据库会自动创建管理员 `admin`，随机密码只在首次创建时输出一次。登录后请前往“设置 -> 账户安全”修改密码。

## 打开服务

| 入口 | 本机地址 |
|---|---|
| 管理控制台 | `http://127.0.0.1:8766/console` |
| 用户入口 | `http://127.0.0.1:8765/login` |
| Reading/Legado 书源 | `http://127.0.0.1:8765/api/subscribe/legado/source` |

局域网设备应把 `127.0.0.1` 换成服务器 IP，例如 `192.168.1.20`。两个端口默认监听 `0.0.0.0`，请使用宿主机防火墙限制管理员端口 `8766` 的访问来源。

如需通过一个固定 IP 或域名直接访问，可设置 `LEGADOHUB_EXTERNAL_HOST`。值只填写主机名，不带协议、端口或路径；该变量只增加允许的 Host，不会配置防火墙、TLS 或公网转发。

Docker Compose：

```bash
LEGADOHUB_EXTERNAL_HOST=example.com docker compose up -d
```

Docker：在主服务的 `docker run` 命令中增加 `-e LEGADOHUB_EXTERNAL_HOST=example.com`。

## 完成首次配置

### 安装官方插件

镜像已经附带第三方插件。官方插件需要单独取得并放入：

```text
plugins/sources/official/<插件 ID>/
```

放置完成后重启服务：

```bash
# Docker Compose
docker compose restart legadohub

# Docker
docker restart legadohub
```

官方源能读取哪些内容，取决于插件能力、目标站状态、登录账号和账号自身权限。

### 创建用户和订阅

1. 管理员登录 `8766` 控制台，在“用户管理”创建普通用户。
2. 保存系统生成的个人授权码，授权码关闭后不再显示。
3. 用户登录 `8765`，搜索小说并选择起始章节创建订阅。
4. “我的书库”出现可读章节后，即可前往 Reading/Legado 阅读。

重置授权码会立即使旧授权码和该用户已有会话失效。删除普通用户会清理该用户的会话、个人订阅和搜索任务，但不会删除仍可供其他用户使用的共享书籍。

## 接入 Reading/Legado

在 Reading/Legado 中导入：

```text
http://<服务器地址>:8765/api/subscribe/legado/source
```

打开“LegadoHub 聚合”的登录页，输入管理员发放的个人授权码。只有后端明确返回用户名时才算登录成功。

聚合书源搜索会按统一评分展示已经入库并发布的共享书和当前启用的第三方书源结果。官方源只参与服务端聚合，不会作为 Reading 直读源暴露；新增、暂停、恢复和归档订阅仍在 Web 控制台完成。

## 数据目录

两种部署方式使用相同的宿主目录：

| 宿主目录 | 内容 |
|---|---|
| `data` | 用户、订阅、共享书库、章节缓存和浏览器资料 |
| `config` | 应用配置和插件 Cookie |
| `generated` | 生成的聚合书源 |
| `runtime` | 插件运行状态 |
| `plugins/sources/thirdparty` | 第三方插件；空目录首次启动时从镜像初始化 |
| `plugins/sources/official` | 人工安装的官方插件 |

替换或删除容器不会删除这些目录。`config` 和备份文件可能包含登录凭据，不要公开上传。

## 更新与备份

Docker Compose 更新：

```bash
docker compose pull
docker compose up -d
docker compose ps
```

Docker 更新：

```bash
docker pull xzixmn/legado-hub:latest
docker rm -f legadohub
```

然后重新执行上方的主服务 `docker run` 命令。宿主目录保持不变，用户、配置和书籍数据不会随容器删除。

备份前先停止服务，并完整备份 `data`、`config`、`generated`、`runtime` 和 `plugins/sources`。备份文件包含 Cookie 和用户数据，应妥善保管。

## 常见问题

### 为什么 Reading 中搜不到刚订阅的书？

Reading 会展示已发布共享书和启用的第三方书源结果。若要阅读服务端持续整理的聚合正文，请先在“我的书库”确认该书已有可读章节；第三方结果则取决于目标站当时是否可访问。

### 为什么有的章节只有预览？

服务不会绕过目标站的付费规则。账号无完整正文权限、来源暂时失败或补充来源尚未通过校验时，章节可能只有预览。

### 为什么书源可达，正文仍然失败？

可达只代表目标站能够连接，不代表页面结构、登录状态或章节权限一定有效。具体原因以书籍详情中的失败信息为准。

### 多个用户可以订阅同一本书吗？

可以。系统只维护一份共享章节数据，每个用户分别保存自己的订阅关系和设置。

### 忘记管理员密码怎么办？

Docker Compose：

```bash
docker compose exec -T legadohub python /app/backend/scripts/reset_user_password.py --username admin
```

Docker：

```bash
docker exec legadohub python /app/backend/scripts/reset_user_password.py --username admin
```

命令会生成新密码并撤销该管理员的现有会话。

## 网络与使用边界

- 本项目不提供公网模式、内置穿透、反向代理或 TLS 配置。
- 自行建立外网访问时，域名、TLS、防火墙、可信代理、限流和管理员入口隔离由部署者负责。
- 仅在有权访问和处理相应内容的前提下使用，并遵守目标站服务条款、当地法律和版权要求。
- 本项目不是 Legado 官方项目，不保证第三方书源持续可用。

问题反馈：[GitHub Issues](https://github.com/XziXmn/legado-hub/issues)
