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

---

## 安全与使用边界

- 默认面向本机或受控局域网部署。如需外网访问，域名、TLS、反向代理、防火墙策略由部署者自行负责。
- 不支持开放注册、匿名阅读或公网模式。
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

提交 PR 前请：
1. 阅读 [AGENTS.md](AGENTS.md) 及相关架构文档，确保改动落在正确边界内
2. 保持单一职责：一个 PR 解决一个明确问题
3. 运行 `verify.ps1` 并在 PR 描述中附上结果
4. 不要提交运行时数据（`data/`、`config/app_config.json`、Cookie、官方插件等）

---

## 友情链接

- [LINUX DO](https://linux.do/)

---

## 许可

本仓库当前未附带 `LICENSE` 文件。在作者明确声明许可协议前，请勿默认按开源许可再分发或商用。

---

[![Docker Image](https://img.shields.io/badge/Docker-xzixmn%2Flegado--hub-2496ED?logo=docker)](https://hub.docker.com/r/xzixmn/legado-hub)
[![GitHub](https://img.shields.io/badge/GitHub-XziXmn-181717?logo=github)](https://github.com/XziXmn/legado-hub)
