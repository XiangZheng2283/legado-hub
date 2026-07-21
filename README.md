<div align="center">
  <h1>小说聚合订阅</h1>
  <p><strong>LegadoHub</strong></p>
  <p>集中维护书源、订阅小说和持续更新章节，最终回到 Reading/Legado 阅读。</p>
  <p>
    <a href="#快速开始">快速开始</a> ·
    <a href="#接入-readinglegado">接入 Reading/Legado</a> ·
    <a href="#更新与备份">更新与备份</a> ·
    <a href="#常见问题">常见问题</a>
  </p>
  <p>
    <img alt="Docker Compose" src="https://img.shields.io/badge/deploy-Docker%20Compose-2496ED?style=flat-square&amp;logo=docker&amp;logoColor=white">
    <img alt="Reading / Legado" src="https://img.shields.io/badge/client-Reading%20%2F%20Legado-2563EB?style=flat-square">
  </p>
</div>

小说聚合订阅是一套面向 Reading/Legado 的自托管订阅服务。管理员维护书源和官方账号，受邀用户使用个人授权码搜索、订阅小说；服务端负责整理章节和检查更新，Reading/Legado 负责日常阅读。

项目默认服务于本机或受控局域网，不提供开放注册、匿名阅读或内置公网模式。

## 使用方式

- 管理员在 Web 控制台维护插件、官方源登录、用户和订阅策略。
- 用户在 Web 控制台搜索小说、创建订阅并查看处理进度。
- 服务端复用共享书库，避免多人订阅同一本书时重复处理。
- Reading/Legado 获取已经入库的目录、正文和来源支持的评论。

Web 控制台是管理和订阅入口，不是主要阅读器。

## 快速开始

### 准备环境

- Git
- Docker
- Docker Compose

官方镜像支持 `linux/amd64` 和 `linux/arm64`，默认部署不需要 `.env`。

### 1. 获取部署文件

```bash
git clone https://github.com/XziXmn/legado-hub.git
cd legado-hub
mkdir -p data config generated runtime plugins/sources/thirdparty plugins/sources/official
```

PowerShell：

```powershell
git clone https://github.com/XziXmn/legado-hub.git
Set-Location legado-hub
New-Item -ItemType Directory -Force data,config,generated,runtime,plugins/sources/thirdparty,plugins/sources/official | Out-Null
```

### 2. 启动

```bash
docker compose pull
docker compose up -d
docker compose ps
```

默认无需设置变量，本机和局域网地址会自动通过 Host 校验。需要通过固定公网 IP
或域名直接访问时，只填写主机名，不带协议、端口或路径：

```bash
LEGADOHUB_EXTERNAL_HOST=54.199.231.36 docker compose up -d
```

PowerShell：

```powershell
$env:LEGADOHUB_EXTERNAL_HOST = "54.199.231.36"
docker compose up -d
```

该变量只额外放行指定 Host；服务仍监听 `0.0.0.0`，本机和局域网访问保持可用。
它不会开放防火墙或提供 TLS，公网部署仍应由使用者配置 HTTPS 和管理端口访问控制。

服务状态变为 `healthy` 后查看首次启动日志：

```bash
docker compose logs legadohub
```

空数据库会自动创建管理员 `admin`，随机密码只在创建时输出一次。登录后请前往“设置 → 账户安全”修改密码。

### 3. 打开服务

| 入口 | 本机地址 |
|---|---|
| 管理控制台 | `http://127.0.0.1:8766/console` |
| 用户入口 | `http://127.0.0.1:8765/login` |
| Reading/Legado 书源 | `http://127.0.0.1:8765/api/subscribe/legado/source` |

局域网设备应把 `127.0.0.1` 换成服务器 IP，例如 `192.168.1.20`。两个端口默认监听 `0.0.0.0`，请使用宿主机防火墙限制管理员端口 `8766` 的访问来源。

## 完成首次配置

### 安装官方插件

镜像已经附带第三方插件。官方插件需要单独取得并放入：

```text
plugins/sources/official/<插件 ID>/
```

然后重启服务：

```bash
docker compose restart legadohub
```

官方源能读取哪些内容，取决于插件能力、目标站状态、登录账号和账号自身权限。

### 创建用户和订阅

1. 管理员登录 `8766` 控制台，在“用户管理”创建普通用户。
2. 保存系统生成的个人授权码。授权码关闭后不再显示。
3. 用户登录 `8765`，搜索小说并选择起始章节创建订阅。
4. “我的书库”出现可读章节后即可前往 Reading/Legado 阅读，剩余章节会继续在后台处理。

重置授权码会立即使旧授权码和该用户已有会话失效。

## 接入 Reading/Legado

在 Reading/Legado 中导入：

```text
http://<服务器地址>:8765/api/subscribe/legado/source
```

导入后打开“LegadoHub 聚合”的登录页，输入管理员发放的个人授权码。只有后端明确返回用户名时才算登录成功。

聚合书源只展示已经入库并发布的共享书。新增、暂停、恢复和归档订阅仍在 Web 控制台完成。

## 数据目录

Docker Compose 会把运行数据和插件映射到项目目录：

| 宿主目录 | 内容 |
|---|---|
| `data` | 用户、订阅、共享书库、章节缓存和浏览器资料 |
| `config` | 应用配置和插件 Cookie |
| `generated` | 生成的聚合书源 |
| `runtime` | 插件运行状态 |
| `plugins/sources/thirdparty` | 第三方插件；空目录首次启动时从镜像初始化 |
| `plugins/sources/official` | 人工安装的官方插件 |

替换容器不会删除这些目录。`config` 和备份文件可能包含登录凭据，不要公开上传。

## 更新与备份

更新前先停止服务并备份映射目录：

```bash
docker compose stop legadohub
tar -czf legadohub-backup.tar.gz data config generated runtime plugins/sources
docker compose start legadohub
```

拉取新版本：

```bash
git pull --ff-only
docker compose pull
docker compose up -d
docker compose ps
```

恢复时停止服务，把备份目录放回原位，再重新启动。备份文件包含 Cookie 和用户数据，应妥善保管。

## 常见问题

### Reading 中为什么搜不到刚订阅的书？

Reading 只展示已经入库并发布的共享书。先在“我的书库”确认是否已有可读章节。

### 为什么有的章节只有预览？

服务不会绕过目标站的付费规则。账号无完整正文权限、来源暂时失败或补充来源尚未通过校验时，章节可能只有预览。

### 为什么书源可达，正文仍然失败？

可达只代表目标站能够连接，不代表页面结构、登录状态或章节权限一定有效。具体原因以书籍详情中的失败信息为准。

### 多个用户可以订阅同一本书吗？

可以。系统只维护一份共享章节数据，每个用户分别保存自己的订阅关系和设置。

### 忘记管理员密码怎么办？

在部署目录执行：

```bash
docker compose exec -T legadohub python /app/backend/scripts/reset_user_password.py --username admin
```

命令会生成新密码并撤销该管理员的现有会话。

## 网络与使用边界

- 本项目不提供公网模式、内置穿透、反向代理或 TLS 配置。
- 自行建立外网访问时，域名、TLS、防火墙、可信代理、限流和管理员入口隔离由部署者负责。
- 仅在有权访问和处理相应内容的前提下使用，并遵守目标站服务条款、当地法律和版权要求。
- 本项目不是 Legado 官方项目，不保证第三方书源持续可用。

问题反馈：[GitHub Issues](https://github.com/XziXmn/legado-hub/issues)
