# LegadoHub

自托管小说聚合订阅服务，为 Reading / Legado 提供稳定的后端书源。

---

## 解决什么问题

用「阅读」看小说的人，多少都被书源折腾过：

- 书源说挂就挂，换源意味着重新搜索、重新登录；
- 多台设备、多人使用，各自维护一套书源，同一本书重复抓取，浪费时间也浪费带宽。

LegadoHub 的做法是把这些麻烦事集中到服务端：**书源由管理员统一维护，章节由服务端统一抓取缓存，读者只要搜索、订阅、阅读。**

- **共享书库**：一本书入库后全站共享。多人订阅同一本书，共用一份章节缓存，阅读进度各记各的；
- **主源失效，候选补全**：正文优先从官方源（主源）获取；主源只给 VIP 预览时，自动从第三方候选源补全完整章节；
- **抓到的就是自己的**：章节抓取后按序缓存落盘，连载期间持续追更。之后源再怎么波动，已入库的章节始终可读；
- **各管各的事**：管理员一次性配好书源和用户，读者只管找书、看书。

```
管理员安装插件、登录官方源 → 创建用户、发放专属书源/订阅链接
                ↓
用户导入专属书源（或打开专属订阅页）→ 无需再输授权码
                ↓
搜索并订阅 → 服务端从主源抓取章节、候选源补全 → Reading 阅读
```

---

## 快速开始

推荐用 Docker Compose 部署；不用 Compose 的话，直接跳到 [Docker CLI](#docker-cli)。

### 前提条件

一台装了 Docker 的机器（NAS、VPS、本地电脑都行），`8765` 和 `8766` 端口空闲。

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

打开 `docker-compose.yml`，通常只有这几处需要留意：

| 配置项 | 说明 |
|--------|------|
| `PUID` / `PGID` | 宿主机用户和组 ID，默认 `1000`，大多数场景不用改 |
| `volumes` 左侧路径 | NAS 用户建议改成绝对路径（文件里附了群晖、飞牛的注释示例） |
| `ports` | 只有端口冲突时才改左侧的宿主端口 |

如果之前改过 `PUID` / `PGID`，或者旧书库的文件属主不对，先执行一次属主修正：

```bash
LEGADOHUB_CHOWN_DATA=1 docker compose up -d --force-recreate legadohub
docker compose up -d --force-recreate legadohub
```

注意：这里不能用 `docker compose restart`，restart 不会加载新的环境变量。

### 3. 启动

```bash
docker compose pull
docker compose up -d
```

镜像比较大（内置 Chromium），首次拉取需要等一会儿。看到容器状态变成 `healthy` 就说明启动完成。顺手验证两个入口：

```bash
curl -s http://127.0.0.1:8765/api/auth/entrypoint   # → "entrypoint":"public"
curl -s http://127.0.0.1:8766/api/auth/entrypoint   # → "entrypoint":"admin"
```

### 4. 获取管理员密码

首次启动会自动创建 `admin` 账号，随机密码只在日志里打印一次：

```bash
docker compose logs legadohub | grep -i password
```

错过了也没关系，直接重置：

```bash
docker compose exec -T legadohub \
  python /app/backend/scripts/reset_user_password.py --username admin
```

登录后建议去 **设置 → 账户安全** 修改密码。

### 5. 初始配置

1. 打开管理后台 `http://服务器IP:8766`，用 `admin` 登录；
2. 安装书源插件：第三方插件已随镜像附带；官方插件需要放入 `plugins/sources/official/` 后重启容器；
3. 在「用户管理」创建普通用户。系统会生成**个人授权码**和**专属链接**（书源导入地址 + 浏览器订阅页），**只在弹窗里显示一次**——关掉就再也看不到明文，请当场复制保存。

### 6. 接入 Reading / Legado

**推荐：发专属书源链接**（用户管理弹窗里「专属书源链接」）

```
http://服务器IP:8765/api/subscribe/legado/source?code=用户的授权码
```

用户在 Reading / Legado 里导入这条链接后，书源已绑定该用户身份：点登录会自动鉴权，「订阅管理」也会直接进入控制台，**不用再手输授权码**。

也可以发「专属订阅页链接」：浏览器打开后自动登录并跳到订阅页，适合先在网页里搜书、建订阅，再回阅读器看书。

**备用：公共书源 + 手输授权码**

```
http://服务器IP:8765/api/subscribe/legado/source
```

公共地址不带 `code`，导入后需在书源登录页粘贴授权码。多人共用同一公共地址时，每个人仍必须用自己的码登录。

导入后在书源管理页启用本书源即可搜索和阅读。从搜索结果进入书籍详情，看到的就是服务端聚合处理后的章节列表。

> **重置授权码**会让旧码、旧专属链接和该用户已有登录会话全部失效。需要重新把弹窗里的新链接发给用户。

### Docker CLI

不用 Compose 时，在已建好数据目录的 `/opt/legado-hub` 下运行：

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

LegadoHub 默认只服务本机和局域网：没配置公网地址时，阅读口只认局域网的 Host，公网访问会被直接拒绝（`400 Host is not allowed`）。这是有意的安全策略——容器本身监听 `0.0.0.0`、可以正常启动，你要做的只是把**对外访问的地址登记进白名单**。

### 公网地址优先级

```
管理后台「设置 → 阅读 → 允许的公网地址」
  > 环境变量 LEGADOHUB_PUBLIC_BASE_URL
  > 仅局域网自动识别
```

- **部署时**：可以在 `docker-compose.yml` 的 `environment` 里写好变量，完成首次引导；
- **之后**：在管理后台保存「允许的公网地址」即可覆盖环境变量，**不用重建容器**；
- **局域网访问不受影响**：内网访问仍按实际 Host 生成内网书源（与公网书源是两套身份，见下文）。

### 1. 环境变量（可选，用于首次引导）

在 `docker-compose.yml` 的 `legadohub.environment` 里加（域名和公网 IP 二选一）：

**域名 + HTTPS（推荐，TLS 在反代上终止）**

```yaml
- LEGADOHUB_PUBLIC_BASE_URL=https://book.example.com
- LEGADOHUB_ALLOWED_HOSTS=book.example.com
- LEGADOHUB_ALLOWED_ORIGINS=https://book.example.com
# 反代所在网段（Docker 网桥 / 本机反代按实际情况填）
- LEGADOHUB_TRUSTED_PROXIES=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.1/32
```

**公网 IP + HTTP 直连（没有域名时）**

```yaml
- LEGADOHUB_PUBLIC_BASE_URL=http://203.0.113.10:8765
- LEGADOHUB_ALLOWED_HOSTS=203.0.113.10
- LEGADOHUB_ALLOWED_ORIGINS=http://203.0.113.10:8765
```

几个容易踩的坑：

| 项 | 要求 |
|----|------|
| origin 格式 | 必须以 `http://` 或 `https://` 开头，**不要带路径**（比如 `/api`） |
| 端口 | 非 80/443 端口必须写进 origin，访问地址也要带上 |
| 前后一致 | 浏览器地址、Reading 导入地址、白名单 origin 的协议/主机/端口必须完全一致 |
| 固定 HTTPS | 一旦 `LEGADOHUB_PUBLIC_BASE_URL` 配成 `https://`，阅读口就只接受 HTTPS |

改完环境变量要重建容器才生效：

```bash
docker compose up -d --force-recreate legadohub
```

### 2. 控制台设置（推荐，可覆盖变量）

1. 先从一个**能访问的入口**打开管理后台：比如内网的 `http://服务器局域网IP:8766`，或防火墙已放行的 `http://公网IP:8766`；
2. 登录后进入 **设置 → 阅读 → 公网访问白名单 → 允许的公网地址**；
3. 填入和对外访问地址一致的 origin，例如：
   - `https://book.example.com`
   - `http://203.0.113.10:8765`
4. 保存立即生效，并且从此**优先于**环境变量 `LEGADOHUB_PUBLIC_BASE_URL`。

### 3. 防火墙与反代建议

| 端口 | 用途 | 建议 |
|------|------|------|
| `8765` | 用户 / Reading 书源 | 可以走域名反代或公网放行，但务必配合授权码使用 |
| `8766` | 管理后台 | **别裸奔**：限制来源 IP、走 VPN，或干脆只对局域网开放 |

TLS 和反向代理（Caddy / Nginx / Cloudflare 等）需要自己配置，应用不内置证书和反代。

### 4. 接入书源（公网）

先在管理后台登记好公网 origin，再去「用户管理」创建或重置用户——弹窗里会按公网地址生成专属链接，直接复制发给用户即可。

也可以手拼公共书源（再让用户自己输授权码）：

```
https://你的域名/api/subscribe/legado/source
# 或
http://你的公网IP:8765/api/subscribe/legado/source
```

地址必须和已登记的公网 origin 一致。若弹窗里没有公网专属链接，多半是还没登记「允许的公网地址」——补上后重新生成授权码即可。

### 5. 公网与局域网双源

| 导入方式 | 书源身份（示意） |
|----------|------------------|
| 公网域名 / 公网 IP | `LegadoHub`（公网） |
| 局域网 IP | `LegadoHub-LAN`（内网，名称带「·内网」） |

两套书源可以同时存在，但授权和进度各自独立。日常建议人在哪个网络就只启用哪一套，免得搜索结果混在一起。

### 6. 自检

```bash
# 容器健康状态
docker compose ps

# 本机入口
curl -s http://127.0.0.1:8765/api/auth/entrypoint
curl -s http://127.0.0.1:8766/api/auth/entrypoint

# 公网入口（换成你的 origin）
curl -sI https://book.example.com/api/auth/entrypoint
```

如果公网返回 `400 Host is not allowed`，说明当前 Host 不在白名单里，或者协议/端口和登记的不一致，回上面两步检查一下。

---

## 两种使用方式

导入聚合书源（建议用个人专属链接）并完成登录后，在 Reading / Legado 里有两种用法：

| 方式 | 说明 |
|------|------|
| **直接搜索第三方源** | 登录后直接在阅读器里搜已启用的第三方书源，随搜随看，不走订阅。适合临时读一本。 |
| **订阅后阅读共享库** | 在订阅控制台（网页或书源里的「订阅管理」）搜索并创建订阅；章节由服务端持续处理：主源抓正文、候选源补全 VIP 预览、结果缓存落盘。源再波动，已入库章节也始终可读。适合长期追更。 |

两种方式可以混着用：搜索结果里既有第三方实时结果，也有已入库的共享库条目。

---

## 功能

| 功能 | 说明 |
|------|------|
| 共享书库 | 每本书入库后全站共享，多人订阅共用一份章节缓存 |
| 主源优先，候选补全 | 正文优先从官方源获取；主源只有 VIP 预览时，自动从第三方候选源补全 |
| 自动追更 | 连载期间持续检查更新，新章节按序抓取入库 |
| 邀请制多用户 | 管理员创建用户、发放独立授权码；每人一条专属书源/订阅链接，导入后免再输码 |
| 凭证可吊销 | 重置授权码后，旧码、旧专属链接和已有会话立即失效 |
| 公网 / 内网双源 | 同一套服务可同时导出公网与局域网书源身份，互不覆盖 |
| 双入口分离 | `8765` 面向用户和阅读器，`8766` 面向管理员（建议只对可信来源开放） |

---

## 常见问题

<details>
<summary>为什么在 Reading 里搜不到刚订阅的书？</summary>

Reading 只展示已发布且有可读章节的书。先到 Web 控制台「我的书库」确认书已发布、并且至少有一章可读。
</details>

<details>
<summary>为什么部分章节只有预览？</summary>

服务不会绕过目标站的付费规则。如果主源账号没有完整权限、所有候选源也没能补全，章节就只能保留预览内容。
</details>

<details>
<summary>书源显示可达，正文还是获取失败？</summary>

「可达」只代表网络能连上，不代表页面结构、登录状态或章节权限没问题。具体原因看书详情页里的错误信息。
</details>

<details>
<summary>多个用户能订阅同一本书吗？</summary>

可以。每本书只有一份共享的章节数据，订阅关系和阅读进度各自独立保存。
</details>

<details>
<summary>忘记管理员密码？</summary>

```bash
docker compose exec -T legadohub \
  python /app/backend/scripts/reset_user_password.py --username admin
```

会生成新密码，同时踢掉该管理员的所有登录会话。
</details>

<details>
<summary>用户授权码丢了怎么办？</summary>

授权码和专属链接只在创建/重置时显示一次，服务端不保留明文。到「用户管理」对该用户点「重新生成订阅凭证」，把**新的**专属书源链接发给对方。旧码、旧链接和已有登录会立刻失效。
</details>

<details>
<summary>导入了公共书源，还要不要输授权码？</summary>

要。公共地址 `.../legado/source` 不含个人身份。用管理员发放的**带 `?code=` 的专属书源链接**导入，才能自动登录；否则请在书源登录页粘贴授权码。
</details>

<details>
<summary>第三方插件目录被清空了？</summary>

重启时如果目录是空的，启动脚本会从镜像里恢复默认的第三方插件。你自己改过的版本不会恢复，除非事先备份过。
</details>

<details>
<summary>公网 VPS 上提示 Host is not allowed？</summary>

阅读口默认不认公网 Host。设置环境变量 `LEGADOHUB_PUBLIC_BASE_URL`（连同 `ALLOWED_HOSTS` / `ALLOWED_ORIGINS`），或在管理后台「设置 → 阅读 → 允许的公网地址」登记与访问地址一致的 origin（域名或公网 IP 都行）。详见 [公网部署](#公网部署vps--域名--公网-ip)。
</details>

---

## 安全与使用边界

- 默认面向本机或受控局域网。要公网访问，请先登记允许的公网 origin（管理后台的设置优先于环境变量），详见 [公网部署](#公网部署vps--域名--公网-ip)。
- TLS、反向代理、防火墙、管理口（`8766`）的暴露范围，都由部署者自己把关；项目不提供开放注册和匿名阅读。
- 专属书源/订阅链接等同于该用户的长期凭证，请通过可信渠道发放；泄漏后立即在「用户管理」重置。
- 请只在有权访问和处理相应内容的前提下使用，遵守目标站点的服务条款和当地法律法规。
- 本项目不是 Legado 官方项目，也不保证任何第三方书源的持续可用性。

---

## 开发者入口

| 主题 | 位置 |
|------|------|
| 仓库结构与本地启动 | [AGENTS.md](AGENTS.md) |
| 书源插件开发规范 | [docs/architecture/source-plugin-contract.zh-CN.md](docs/architecture/source-plugin-contract.zh-CN.md) |
| 插件编写教程 | [docs/skills/book-source-craft/README.md](docs/skills/book-source-craft/README.md) |
| 产品边界与设计原则 | [docs/PRODUCT.md](docs/PRODUCT.md) |
| 完整校验脚本 | `verify.ps1` |

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

也可以直接跑 `.\start.bat`。

---

## 贡献

问题反馈和功能建议，欢迎到 [GitHub Issues](https://github.com/XziXmn/legado-hub/issues) 提。

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
