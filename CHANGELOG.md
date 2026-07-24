# Changelog

格式大致遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。  
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

镜像通道见 README「镜像通道」：`beta` = 开发测试，`vX.Y.Z` / `latest` = 正式发行。

书源规则版本（Reading 名称里的 `0.x.y`）只在**正式发版**时递增；日常 beta 只推进 `lastUpdateTime` 时间戳，避免版本号刷屏。

## [0.2.0] - 2026-07-24

书源规则版本：`0.0.26`。

### 新增

- 专属书源强制携带 `code`，搜索、目录与正文统一静默兑换用户会话
- Docker 部署变量 `LEGADOHUB_PUBLIC_BASE_URL` 可预设公网专属书源地址；后台设置保存后立即覆盖该默认值

### 变更

- 公网 Host 是否可达交由防火墙、WAF 或反向代理控制；应用继续校验 Host 语法并阻止公网客户端伪造局域网 Host
- Reading 登录页精简为“订阅 / 书库”，专属书源不再要求用户重复输入授权码
- 公网与局域网书源、搜索状态和会话保持独立，避免客户端合并同一本书的两条网络链路

### 修复

- 书源内控制台链接错误指向管理端口，现统一使用阅读端口
- Reading 请求头异步调用阻断登录面板，以及不同客户端对登录脚本兼容不一致
- 用户凭证弹窗在 HTTP 局域网环境无法复制，并统一创建、重置后的凭证展示
- 部署变量与后台“公网书源地址”契约漂移；恢复“后台设置 > 环境变量 > 请求地址”的链接生成优先级
- 升级 React Router 至 7.18.1，修复公开披露的重定向、XSS 与反序列化安全问题

### 镜像

| 通道 | Tag |
|------|-----|
| 正式 | `xzixmn/legado-hub:v0.2.0`、`xzixmn/legado-hub:latest` |
| 开发测试 | `xzixmn/legado-hub:beta` |
| 精确定位 | `xzixmn/legado-hub:sha-<commit>` |

## [0.1.0] - 2026-07-24

首个正式发行。书源规则版本：`0.0.20`。

### 新增

- 个人专属书源 / 订阅链接：授权码写入 `?code=`，Reading 静默鉴权；Web 订阅页经 `/api/auth/access/enter` 免再输码
- 用户管理：创建/重置授权码时展示可复制的公网/内网专属链接
- 公网与局域网双书源身份（`LegadoHub` / `LegadoHub-LAN`）与搜索分轨
- 阅读口设置「允许的公网地址」优先于环境变量引导

### 修复

- 管理台 HTTP 局域网下复制按钮（Clipboard API 回退）
- 多种 69 书吧混淆水印（含 `6.9ꁘ書吧`、`6=9+` 残片等）
- 绑定专属源登录页仅保留「订阅管理 / 退出」；请求头静默兑换会话，减少「点击登录去授权」
- 插件正则内联 flags 等稳定性问题

### 文档

- README：公网部署、专属链接、镜像通道说明

### 镜像

| 通道 | Tag |
|------|-----|
| 正式 | `xzixmn/legado-hub:v0.1.0`、`xzixmn/legado-hub:latest` |
| 开发测试 | `xzixmn/legado-hub:beta`（随 main 滚动） |
| 精确定位 | `xzixmn/legado-hub:sha-<commit>` |

[0.1.0]: https://github.com/XziXmn/legado-hub/releases/tag/v0.1.0
[0.2.0]: https://github.com/XziXmn/legado-hub/releases/tag/v0.2.0
