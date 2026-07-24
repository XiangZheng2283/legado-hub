# Changelog

格式大致遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。  
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

镜像通道见 README「镜像通道」：`beta` = 开发测试，`vX.Y.Z` / `latest` = 正式发行。

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
