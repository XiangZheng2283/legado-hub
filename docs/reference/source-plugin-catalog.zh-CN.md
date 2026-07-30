# 书源插件档案

本文件由全部 `plugins/sources/*/*/metadata.yaml` 生成，是书源运行声明的可读索引。
字段显示“未声明”代表插件没有在元数据中承诺该能力或限制，不能据此推断运行时行为。
修改元数据后执行 `python backend/scripts/generate_source_plugin_catalog.py` 更新本文件。

## 总览

- 已收录：`36` 个插件。
- 运行时契约：[`source-plugin-contract.zh-CN.md`](../architecture/source-plugin-contract.zh-CN.md)。
- 浏览器仅由宿主 Access Bridge 管理；本档案的浏览器字段不表示挑战绕过或令牌缓存。

| 分类 | 插件 | 版本 | 语言 | 浏览器 | 代理 | 限流 |
| --- | --- | --- | --- | --- | --- | --- |
| official | 起点中文网(App) (`qidian_com_app`) | 0.2.9 | zh-CN | optional | auto | -/-ms |
| official | 起点中文网(Web) (`qidian_com_web`) | 0.1.7 | zh-CN | optional | auto | -/-ms |
| thirdparty | 零点小说 (`0xs_net`) | 0.1.1 | zh-CN | optional | auto | 3/1000ms |
| thirdparty | 69书屋 (`69hsw_com`) | 0.1.4 | zh-CN | none | auto | 3/1200ms |
| thirdparty | 69书吧 (`69shuba_com`) | 0.1.5 | zh-CN | optional | always (required) | 3/1200ms |
| thirdparty | 69書吧繁體 (`69shuba_tw`) | 0.1.1 | zh-TW | required | always (required) | 3/1200ms |
| thirdparty | 96读书 (`96dushu_com`) | 0.1.2 | zh-CN | none | auto | 3/900ms |
| thirdparty | 笔趣阁365 (`biquge365_net`) | 0.1.2 | zh-CN | none | auto | 6/600ms |
| thirdparty | 小说狂人 (`czbooks_net`) | 0.1.0 | zh-CN | none | auto | 3/1200ms |
| thirdparty | 东滩小说 (`dongtanxs_com`) | 0.1.1 | zh-CN | none | auto | 6/600ms |
| thirdparty | 独行小说 (`dxtxt_cc`) | 0.1.0 | zh-CN | none | auto | 3/1200ms |
| thirdparty | 黄金屋中文 (`hjwzw_com`) | 0.1.1 | zh-CN | none | auto | 6/600ms |
| thirdparty | 爱下电子书 (`ixdzs8_com`) | 0.1.0 | zh-CN | optional | auto | 3/1200ms |
| thirdparty | 101看书网 (`kks101_com`) | 0.1.1 | zh-CN | optional | always (required) | 3/1200ms |
| thirdparty | 零点看书 (`lingdiankanshu_com`) | 0.1.1 | zh-CN | none | auto | 6/800ms |
| thirdparty | 明智屋 (`mingzw_tw`) | 0.1.1 | zh-CN | none | auto | 6/700ms |
| thirdparty | 新御书屋 (`qianyezw_com`) | 0.1.0 | zh-CN | none | auto | 6/1000ms |
| thirdparty | 企鹅小说 (`qiexs_cc`) | 0.1.0 | zh-CN | none | auto | 3/1200ms |
| thirdparty | 全本小说网 (`quanben5_com`) | 0.1.1 | zh-CN | none | auto | 6/900ms |
| thirdparty | 缺小说 (`quexs_org`) | 0.1.0 | zh-CN | none | auto | 6/1200ms |
| thirdparty | 燃文小说网 (`ranwen8_cc`) | 0.1.1 | zh-CN | none | auto | 3/1200ms |
| thirdparty | 书海阁小说网 (`shuhaige_net`) | 0.1.1 | zh-CN | none | auto | 3/1200ms |
| thirdparty | 书迷楼 (`shumilou_co`) | 0.1.1 | zh-CN | none | auto | 3/1200ms |
| thirdparty | 书迷楼 (`shumilou_top`) | 0.1.1 | zh-CN | none | auto | 6/800ms |
| thirdparty | 思兔阅读 (`sto_com`) | 0.1.1 | zh-CN | none | auto | 6/700ms |
| thirdparty | 速读谷 (`sudugu_org`) | 0.1.3 | zh-CN | none | auto | 3/1200ms |
| thirdparty | 随心看 (`suixkan_com`) | 0.1.0 | zh-CN | none | auto | 3/1200ms |
| thirdparty | 新天禧小说 (`tianxibook_com`) | 0.1.1 | zh-CN | none | auto | 3/1000ms |
| thirdparty | 天天看书网 (`ttkan_co`) | 0.1.2 | zh-CN | none | always (required) | 6/600ms |
| thirdparty | 台灣小說網 (`twkan_com`) | 0.1.5 | zh-CN | optional | auto | 3/1000ms |
| thirdparty | UU阅读 (`uuread_tw`) | 0.1.1 | zh-CN | none | auto | 6/900ms |
| thirdparty | 香书小说 (`xbiqugu_la`) | 0.1.2 | zh-CN | none | auto | 3/1200ms |
| thirdparty | 黄易天地 (`xhytd_com`) | 0.2.0 | zh-CN | none | auto | 3/1200ms |
| thirdparty | 小说虎 (`xiaoshuohu_com`) | 0.1.2 | zh-CN | none | auto | 6/1000ms |
| thirdparty | 夜伴书屋 (`yeban360_com`) | 0.1.0 | zh-CN | none | auto | 6/1200ms |
| thirdparty | 宙斯小说网 (`zhswx_tw`) | 0.1.1 | zh-CN | none | auto | 6/700ms |

# official

## 起点中文网(App) (`qidian_com_app`)

- 目录：`plugins/sources/official/qidian_com_app`；展示名称：起点中文网(App)
- 实现：[`source.py`](../../plugins/sources/official/qidian_com_app/source.py)；说明：[`README.md`](../../plugins/sources/official/qidian_com_app/README.md)
- 分类：`official`；版本：`0.2.9`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.qidian.com`、`https://m.qidian.com`、`https://druidv6.if.qidian.com`
- 域名：`qidian.com`、`www.qidian.com`、`m.qidian.com`、`if.qidian.com`
- 能力：`search`、`detail`、`toc`、`chapter`、`chapter_reviews`、`explore`、`auth`
- 标签：`official`、`login`、`paid`、`json-api`、`mobile-api`、`app-api`
- 登录：模式 `optional`；Cookie 域名：`qidian.com`、`www.qidian.com`、`m.qidian.com`、`yuewen.com`、`ptlogin.qidian.com`、`ptlogin.yuewen.com`
- 内容：访问权限 `mixed`；来源角色 `official`
- 访问策略：未声明
- 浏览器：模式 `optional`；原因 `official_login`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `未声明`；最小间隔 `未声明` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`manual`；`upstreamId`=`qidian`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 起点中文网(Web) (`qidian_com_web`)

- 目录：`plugins/sources/official/qidian_com_web`；展示名称：起点中文网(Web)
- 实现：[`source.py`](../../plugins/sources/official/qidian_com_web/source.py)；说明：[`README.md`](../../plugins/sources/official/qidian_com_web/README.md)
- 分类：`official`；版本：`0.1.7`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.qidian.com`、`https://m.qidian.com`
- 域名：`qidian.com`、`www.qidian.com`、`m.qidian.com`
- 能力：`search`、`detail`、`toc`、`chapter`、`chapter_reviews`、`explore`、`auth`
- 标签：`official`、`login`、`paid`、`json-api`、`mobile-api`
- 登录：模式 `optional`；Cookie 域名：`qidian.com`、`www.qidian.com`、`m.qidian.com`、`yuewen.com`、`ptlogin.qidian.com`、`ptlogin.yuewen.com`
- 内容：访问权限 `mixed`；来源角色 `official`
- 访问策略：未声明
- 浏览器：模式 `optional`；原因 `official_login`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `未声明`；最小间隔 `未声明` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`manual`；`upstreamId`=`qidian`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条


# thirdparty

## 零点小说 (`0xs_net`)

- 目录：`plugins/sources/thirdparty/0xs_net`；展示名称：零点小说
- 实现：[`source.py`](../../plugins/sources/thirdparty/0xs_net/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/0xs_net/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://m.0xs.net`
- 域名：`0xs.net`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`rate_limit`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `optional`；原因 `移动站首次返回 403 时仅用于建立会话，后续详情、目录和正文继续走 HTTP`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1000` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：未声明
- 正文净化规则：`0` 条

## 69书屋 (`69hsw_com`)

- 目录：`plugins/sources/thirdparty/69hsw_com`；展示名称：69书屋
- 实现：[`source.py`](../../plugins/sources/thirdparty/69hsw_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/69hsw_com/README.md)
- 分类：`thirdparty`；版本：`0.1.4`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.69hsw.com`
- 域名：`69hsw.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`captcha-search`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `search_captcha_auto_solved`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：
  - `primary`：`id`=`primary`；`baseUrl`=`https://www.69hsw.com`；`domains`=`www.69hsw.com`、`69hsw.com`；`role`=`desktop`；`fallback`=`True`
- 来源追溯：`type`=`live-site`；`upstreamId`=`69hsw_com`；`upstreamFile`=`https://www.69hsw.com/`；`upstreamCommit`=空
- 正文净化规则：`9` 条
  - `无错版本在读`
  - `首发本小说`
  - `6\s*[=＝]\s*9\s*[+＋]?\s*书[_＿\s]*吧`
  - `6\s*[=＝]\s*9\s*[+＋]`
  - `新?69\s*书\s*[吧屋]`
  - `正确内.?容在`
  - `[%％]\s*六九\s*[%％]`
  - `书[''′]?\s*吧\s*读`
  - `最新网址|返回目录|加入书签|推荐阅读|新书推荐`

## 69书吧 (`69shuba_com`)

- 目录：`plugins/sources/thirdparty/69shuba_com`；展示名称：69书吧
- 实现：[`source.py`](../../plugins/sources/thirdparty/69shuba_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/69shuba_com/README.md)
- 分类：`thirdparty`；版本：`0.1.5`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.69shuba.com`、`https://www.69shuba.cx`
- 域名：`69shuba.com`、`69shuba.cx`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`proxy`、`cloudflare`、`impersonate`
- 登录：模式 `none`；Cookie 域名：`69shuba.com`、`www.69shuba.com`、`69shuba.cx`、`www.69shuba.cx`
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`search_provider`；`detail`=`stealth_http`；`toc`=`stealth_http`；`chapter`=`stealth_http`
- 浏览器：模式 `optional`；原因 `cloudflare_session_refresh`
- 代理：模式 `always`；必需 `True`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：`providerOrder`=`duckduckgo_ddgs`、`bing_html`、`google_html`；`targetDomain`=`www.69shuba.com`；`querySitePath`=`/book`；`urlPatterns`=`/(?:book|txt)/\d+\.htm`、`/book/\d+`
- Access Bridge：`search`=`providers`=`duckduckgo_ddgs`、`bing_html`、`google_html`
- 域名配置：
  - `primary`：`id`=`primary`；`baseUrl`=`https://www.69shuba.com`；`domains`=`www.69shuba.com`、`69shuba.com`；`role`=`desktop`；`fallback`=`True`
  - `mirror_cx`：`id`=`mirror_cx`；`baseUrl`=`https://www.69shuba.cx`；`domains`=`www.69shuba.cx`、`69shuba.cx`；`role`=`mirror`；`fallback`=`True`
- 来源追溯：`type`=`legado`；`upstreamId`=`69shuba_com`；`upstreamFile`=`by-site/legado/69shuba.com.json`；`upstreamCommit`=空
- 正文净化规则：`9` 条
  - `无错版本在读`
  - `首发本小说`
  - `6\s*[=＝]\s*9\s*[+＋]?\s*书[_＿\s]*吧`
  - `6\s*[=＝]\s*9\s*[+＋]`
  - `新?69\s*书\s*吧`
  - `正确内.?容在`
  - `[%％]\s*六九\s*[%％]`
  - `书[''′]?\s*吧\s*读`
  - `阅读sto55|爱75奇书屋`

## 69書吧繁體 (`69shuba_tw`)

- 目录：`plugins/sources/thirdparty/69shuba_tw`；展示名称：69書吧繁體
- 实现：[`source.py`](../../plugins/sources/thirdparty/69shuba_tw/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/69shuba_tw/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-TW`；默认启用：`True`；优先级：`50`
- 主地址：`https://69shuba.tw`
- 域名：`69shuba.tw`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`proxy`、`browser-fetch`、`traditional-chinese`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`headless_browser`；`detail`=`headless_browser`；`toc`=`headless_browser`；`chapter`=`headless_browser`
- 浏览器：模式 `required`；原因 `aegis_browser_context`
- 代理：模式 `always`；必需 `True`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：
  - `mobile`：`id`=`mobile`；`baseUrl`=`https://69shuba.tw`；`domains`=`69shuba.tw`；`role`=`mobile`；`fallback`=`False`
- 来源追溯：`type`=`live`；`upstreamId`=`69shuba_tw`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 96读书 (`96dushu_com`)

- 目录：`plugins/sources/thirdparty/96dushu_com`；展示名称：96读书
- 实现：[`source.py`](../../plugins/sources/thirdparty/96dushu_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/96dushu_com/README.md)
- 分类：`thirdparty`；版本：`0.1.2`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.96dushu.com`
- 域名：`96dushu.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`cloudflare`、`js_encrypted`、`search_provider`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`search_provider`
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `900` ms
- 搜索提供器：`providerOrder`=`bing_html`、`google_html`；`targetDomain`=`www.96dushu.com`；`querySitePath`=`/book`；`urlPatterns`=`/book/\d+/`
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：未声明
- 正文净化规则：`0` 条

## 笔趣阁365 (`biquge365_net`)

- 目录：`plugins/sources/thirdparty/biquge365_net`；展示名称：笔趣阁365
- 实现：[`source.py`](../../plugins/sources/thirdparty/biquge365_net/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/biquge365_net/README.md)
- 分类：`thirdparty`；版本：`0.1.2`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://m.biquge365.net`
- 域名：`m.biquge365.net`、`biquge365.net`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`so-novel-seed`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `600` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：
  - `mobile`：`id`=`mobile`；`baseUrl`=`https://m.biquge365.net`；`domains`=`m.biquge365.net`；`role`=`mobile`；`fallback`=`True`
  - `desktop`：`id`=`desktop`；`baseUrl`=`https://www.biquge365.net`；`domains`=`www.biquge365.net`；`role`=`desktop`；`fallback`=`True`
- 来源追溯：`type`=`so-novel`；`upstreamId`=`www_biquge365_net`；`upstreamFile`=`bundle/rules/main.json`；`upstreamCommit`=`bfb5fda1d6ea04ad7f30a761640e08ce2e5db0e0`
- 正文净化规则：`0` 条

## 小说狂人 (`czbooks_net`)

- 目录：`plugins/sources/thirdparty/czbooks_net`；展示名称：小说狂人
- 实现：[`source.py`](../../plugins/sources/thirdparty/czbooks_net/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/czbooks_net/README.md)
- 分类：`thirdparty`；版本：`0.1.0`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`40`
- 主地址：`https://czbooks.net`
- 域名：`czbooks.net`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`traditional-chinese`、`cloudflare`、`rate_limit`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`stealth_http`；`detail`=`stealth_http`；`toc`=`stealth_http`；`chapter`=`stealth_http`
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`czbooks_net`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 东滩小说 (`dongtanxs_com`)

- 目录：`plugins/sources/thirdparty/dongtanxs_com`；展示名称：东滩小说
- 实现：[`source.py`](../../plugins/sources/thirdparty/dongtanxs_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/dongtanxs_com/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`http://www.dongtanxs.com`
- 域名：`dongtanxs.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`cloudflare`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `600` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：未声明
- 正文净化规则：`0` 条

## 独行小说 (`dxtxt_cc`)

- 目录：`plugins/sources/thirdparty/dxtxt_cc`；展示名称：独行小说
- 实现：[`source.py`](../../plugins/sources/thirdparty/dxtxt_cc/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/dxtxt_cc/README.md)
- 分类：`thirdparty`；版本：`0.1.0`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`40`
- 主地址：`http://www.dxtxt.cc`
- 域名：`www.dxtxt.cc`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`simplified-chinese`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`http`；`detail`=`http`；`toc`=`http`；`chapter`=`http`
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`dxtxt_cc`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 黄金屋中文 (`hjwzw_com`)

- 目录：`plugins/sources/thirdparty/hjwzw_com`；展示名称：黄金屋中文
- 实现：[`source.py`](../../plugins/sources/thirdparty/hjwzw_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/hjwzw_com/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://tw.hjwzw.com`
- 域名：`tw.hjwzw.com`、`hjwzw.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`traditional-chinese`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `600` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`hjwzw_com`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 爱下电子书 (`ixdzs8_com`)

- 目录：`plugins/sources/thirdparty/ixdzs8_com`；展示名称：爱下电子书
- 实现：[`source.py`](../../plugins/sources/thirdparty/ixdzs8_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/ixdzs8_com/README.md)
- 分类：`thirdparty`；版本：`0.1.0`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`20`
- 主地址：`https://ixdzs8.com`
- 域名：`ixdzs8.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`json-api`、`no-login`、`browser-fallback`
- 登录：模式 `none`；Cookie 域名：`ixdzs8.com`
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`http`；`detail`=`http`；`toc`=`api`；`chapter`=`headless_browser`
- 浏览器：模式 `optional`；原因 `js_challenge`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`ixdzs8_com`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 101看书网 (`kks101_com`)

- 目录：`plugins/sources/thirdparty/kks101_com`；展示名称：101看书网
- 实现：[`source.py`](../../plugins/sources/thirdparty/kks101_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/kks101_com/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://101kks.com`
- 域名：`101kks.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`ajax-api`、`no-login`、`cloudflare`、`browser-bypass`、`search-provider`
- 登录：模式 `none`；Cookie 域名：`101kks.com`
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `optional`；原因 `cloudflare_challenge`
- 代理：模式 `always`；必需 `True`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：`providerOrder`=`duckduckgo_ddgs`、`bing_html`、`google_html`；`targetDomain`=`101kks.com`；`querySitePath`=`/book`；`urlPatterns`=`/book/\d+\.html`、`/book/\d+`
- Access Bridge：`search`=`providers`=`duckduckgo_ddgs`、`bing_html`、`google_html`
- 域名配置：未声明
- 来源追溯：`type`=`manual`；`upstreamId`=`101kks.com`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 零点看书 (`lingdiankanshu_com`)

- 目录：`plugins/sources/thirdparty/lingdiankanshu_com`；展示名称：零点看书
- 实现：[`source.py`](../../plugins/sources/thirdparty/lingdiankanshu_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/lingdiankanshu_com/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`20`
- 主地址：`http://23.225.143.226`
- 域名：`23.225.143.226`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`raw-ip`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`http`；`detail`=`http`；`toc`=`http`；`chapter`=`http`
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `800` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`lingdiankanshu_com`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 明智屋 (`mingzw_tw`)

- 目录：`plugins/sources/thirdparty/mingzw_tw`；展示名称：明智屋
- 实现：[`source.py`](../../plugins/sources/thirdparty/mingzw_tw/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/mingzw_tw/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://tw.mingzw.net`
- 域名：`tw.mingzw.net`、`mingzw.net`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`traditional-chinese`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `700` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`mingzw_tw`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 新御书屋 (`qianyezw_com`)

- 目录：`plugins/sources/thirdparty/qianyezw_com`；展示名称：新御书屋
- 实现：[`source.py`](../../plugins/sources/thirdparty/qianyezw_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/qianyezw_com/README.md)
- 分类：`thirdparty`；版本：`0.1.0`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.qianyezw.com`
- 域名：`www.qianyezw.com`、`qianyezw.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `1000` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`qianyezw_com`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 企鹅小说 (`qiexs_cc`)

- 目录：`plugins/sources/thirdparty/qiexs_cc`；展示名称：企鹅小说
- 实现：[`source.py`](../../plugins/sources/thirdparty/qiexs_cc/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/qiexs_cc/README.md)
- 分类：`thirdparty`；版本：`0.1.0`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`40`
- 主地址：`http://www.qiexs.cc`
- 域名：`www.qiexs.cc`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`simplified-chinese`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`http`；`detail`=`http`；`toc`=`http`；`chapter`=`http`
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`qiexs_cc`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 全本小说网 (`quanben5_com`)

- 目录：`plugins/sources/thirdparty/quanben5_com`；展示名称：全本小说网
- 实现：[`source.py`](../../plugins/sources/thirdparty/quanben5_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/quanben5_com/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.quanben5.com`
- 域名：`quanben5.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`proxy`、`search_encrypted`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `900` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：未声明
- 正文净化规则：`0` 条

## 缺小说 (`quexs_org`)

- 目录：`plugins/sources/thirdparty/quexs_org`；展示名称：缺小说
- 实现：[`source.py`](../../plugins/sources/thirdparty/quexs_org/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/quexs_org/README.md)
- 分类：`thirdparty`；版本：`0.1.0`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`40`
- 主地址：`http://www.quexs.biz`
- 域名：`www.quexs.biz`、`www.quexs.org`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`simplified-chinese`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`http`；`detail`=`http`；`toc`=`http`；`chapter`=`http`
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`quexs_org`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 燃文小说网 (`ranwen8_cc`)

- 目录：`plugins/sources/thirdparty/ranwen8_cc`；展示名称：燃文小说网
- 实现：[`source.py`](../../plugins/sources/thirdparty/ranwen8_cc/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/ranwen8_cc/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.ranwen8.cc`
- 域名：`ranwen8.cc`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`base64`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：未声明
- 正文净化规则：`0` 条

## 书海阁小说网 (`shuhaige_net`)

- 目录：`plugins/sources/thirdparty/shuhaige_net`；展示名称：书海阁小说网
- 实现：[`source.py`](../../plugins/sources/thirdparty/shuhaige_net/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/shuhaige_net/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.shuhaige.net`
- 域名：`www.shuhaige.net`、`shuhaige.net`、`img.shuhaige.net`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`so-novel-seed`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`so-novel`；`upstreamId`=`www_shuhaige_net`；`upstreamFile`=`bundle/rules/main.json`；`upstreamCommit`=`bfb5fda1d6ea04ad7f30a761640e08ce2e5db0e0`
- 正文净化规则：`0` 条

## 书迷楼 (`shumilou_co`)

- 目录：`plugins/sources/thirdparty/shumilou_co`；展示名称：书迷楼
- 实现：[`source.py`](../../plugins/sources/thirdparty/shumilou_co/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/shumilou_co/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.shumilou.co`
- 域名：`www.shumilou.co`、`shumilou.co`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`paginated-catalog`、`paginated-chapter`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`shumilou_co`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 书迷楼 (`shumilou_top`)

- 目录：`plugins/sources/thirdparty/shumilou_top`；展示名称：`书迷楼（top）`
- 实现：[`source.py`](../../plugins/sources/thirdparty/shumilou_top/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/shumilou_top/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.shumilou.top`
- 域名：`www.shumilou.top`、`shumilou.top`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `800` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`shumilou_top`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 思兔阅读 (`sto_com`)

- 目录：`plugins/sources/thirdparty/sto_com`；展示名称：思兔阅读
- 实现：[`source.py`](../../plugins/sources/thirdparty/sto_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/sto_com/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://sto9.com`
- 域名：`sto9.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`traditional-chinese`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `700` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`sto_com`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 速读谷 (`sudugu_org`)

- 目录：`plugins/sources/thirdparty/sudugu_org`；展示名称：速读谷
- 实现：[`source.py`](../../plugins/sources/thirdparty/sudugu_org/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/sudugu_org/README.md)
- 分类：`thirdparty`；版本：`0.1.3`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.sudugu.org`
- 域名：`sudugu.org`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`proxy`、`rate_limit`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：未声明
- 正文净化规则：`0` 条

## 随心看 (`suixkan_com`)

- 目录：`plugins/sources/thirdparty/suixkan_com`；展示名称：随心看
- 实现：[`source.py`](../../plugins/sources/thirdparty/suixkan_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/suixkan_com/README.md)
- 分类：`thirdparty`；版本：`0.1.0`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`40`
- 主地址：`https://m.suixkan.com`
- 域名：`m.suixkan.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`simplified-chinese`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`http`；`detail`=`http`；`toc`=`http`；`chapter`=`http`
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`suixkan_com`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 新天禧小说 (`tianxibook_com`)

- 目录：`plugins/sources/thirdparty/tianxibook_com`；展示名称：新天禧小说
- 实现：[`source.py`](../../plugins/sources/thirdparty/tianxibook_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/tianxibook_com/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.tianxibook.com`
- 域名：`tianxibook.com`、`sososhu.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1000` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：未声明
- 正文净化规则：`0` 条

## 天天看书网 (`ttkan_co`)

- 目录：`plugins/sources/thirdparty/ttkan_co`；展示名称：天天看书网
- 实现：[`source.py`](../../plugins/sources/thirdparty/ttkan_co/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/ttkan_co/README.md)
- 分类：`thirdparty`；版本：`0.1.2`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.ttkan.co`
- 域名：`ttkan.co`、`static.ttkan.co`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`amp`
- 登录：模式 `none`；Cookie 域名：`ttkan.co`
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `always`；必需 `True`
- 限流：每主机并发 `6`；最小间隔 `600` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`manual`；`upstreamId`=`ttkan.co`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 台灣小說網 (`twkan_com`)

- 目录：`plugins/sources/thirdparty/twkan_com`；展示名称：台灣小說網
- 实现：[`source.py`](../../plugins/sources/thirdparty/twkan_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/twkan_com/README.md)
- 分类：`thirdparty`；版本：`0.1.5`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://twkan.com`
- 域名：`twkan.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`ajax-api`、`no-login`、`proxy`、`impersonate`、`browser-fallback`
- 登录：模式 `none`；Cookie 域名：`twkan.com`
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`stealth_http`；`detail`=`stealth_http`；`toc`=`stealth_http`；`chapter`=`stealth_http`
- 浏览器：模式 `optional`；原因 `cloudflare_challenge`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1000` ms
- 搜索提供器：`providerOrder`=`bing_html`、`google_html`；`targetDomain`=`twkan.com`；`querySitePath`=`/book`；`urlPatterns`=`/book/\d+\.html`、`/book/\d+`、`/txt/\d+/\d+`
- Access Bridge：未声明
- 域名配置：
  - `primary`：`id`=`primary`；`baseUrl`=`https://twkan.com`；`domains`=`twkan.com`；`role`=`desktop`；`fallback`=`True`
- 来源追溯：未声明
- 正文净化规则：`0` 条

## UU阅读 (`uuread_tw`)

- 目录：`plugins/sources/thirdparty/uuread_tw`；展示名称：UU阅读
- 实现：[`source.py`](../../plugins/sources/thirdparty/uuread_tw/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/uuread_tw/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`http://www.uuread.tw`
- 域名：`www.uuread.tw`、`uuread.tw`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`traditional-chinese`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `900` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`uuread_tw`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 香书小说 (`xbiqugu_la`)

- 目录：`plugins/sources/thirdparty/xbiqugu_la`；展示名称：香书小说
- 实现：[`source.py`](../../plugins/sources/thirdparty/xbiqugu_la/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/xbiqugu_la/README.md)
- 分类：`thirdparty`；版本：`0.1.2`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.xbiqugu.com`
- 域名：`xbiqugu.com`、`xbiqugu.la`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`so-novel-seed`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：
  - `current`：`id`=`current`；`baseUrl`=`https://www.xbiqugu.com`；`domains`=`www.xbiqugu.com`；`role`=`desktop`；`fallback`=`True`
  - `legacy`：`id`=`legacy`；`baseUrl`=`http://www.xbiqugu.la`；`domains`=`www.xbiqugu.la`；`role`=`legacy`；`fallback`=`True`
- 来源追溯：`type`=`so-novel`；`upstreamId`=`www_xbiqugu_la`；`upstreamFile`=`bundle/rules/main.json`；`upstreamCommit`=`bfb5fda1d6ea04ad7f30a761640e08ce2e5db0e0`
- 正文净化规则：`3` 条
  - `最新章节地址`
  - `请收藏.*xbiqugu`
  - `手机用户请浏览`

## 黄易天地 (`xhytd_com`)

- 目录：`plugins/sources/thirdparty/xhytd_com`；展示名称：黄易天地
- 实现：[`source.py`](../../plugins/sources/thirdparty/xhytd_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/xhytd_com/README.md)
- 分类：`thirdparty`；版本：`0.2.0`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`http://wap.xhytd.com`
- 域名：`xhytd.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`cloudflare`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `3`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：未声明
- 正文净化规则：`0` 条

## 小说虎 (`xiaoshuohu_com`)

- 目录：`plugins/sources/thirdparty/xiaoshuohu_com`；展示名称：小说虎
- 实现：[`source.py`](../../plugins/sources/thirdparty/xiaoshuohu_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/xiaoshuohu_com/README.md)
- 分类：`thirdparty`；版本：`0.1.2`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`50`
- 主地址：`https://www.xiaoshuohu.com`
- 域名：`xiaoshuohu.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`ads`、`search_provider`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`search_provider`
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `1000` ms
- 搜索提供器：`providerOrder`=`bing_html`、`google_html`；`targetDomain`=`www.xiaoshuohu.com`；`querySitePath`=`/`；`urlPatterns`=`/\d+/\d+/?$`
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：未声明
- 正文净化规则：`0` 条

## 夜伴书屋 (`yeban360_com`)

- 目录：`plugins/sources/thirdparty/yeban360_com`；展示名称：夜伴书屋
- 实现：[`source.py`](../../plugins/sources/thirdparty/yeban360_com/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/yeban360_com/README.md)
- 分类：`thirdparty`；版本：`0.1.0`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`40`
- 主地址：`https://www.yeban360.com`
- 域名：`www.yeban360.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`simplified-chinese`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：`search`=`http`；`detail`=`http`；`toc`=`http`；`chapter`=`http`
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `1200` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`yeban360_com`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条

## 宙斯小说网 (`zhswx_tw`)

- 目录：`plugins/sources/thirdparty/zhswx_tw`；展示名称：宙斯小说网
- 实现：[`source.py`](../../plugins/sources/thirdparty/zhswx_tw/source.py)；说明：[`README.md`](../../plugins/sources/thirdparty/zhswx_tw/README.md)
- 分类：`thirdparty`；版本：`0.1.1`；作者：`Yunwei`
- 语言：`zh-CN`；默认启用：`True`；优先级：`40`
- 主地址：`https://tw.zhswx.com`
- 域名：`tw.zhswx.com`
- 能力：`search`、`detail`、`toc`、`chapter`
- 标签：`html`、`no-login`、`traditional-chinese`
- 登录：模式 `none`；Cookie 域名：未声明
- 内容：访问权限 `free`；来源角色 `未声明`
- 访问策略：未声明
- 浏览器：模式 `none`；原因 `未声明`
- 代理：模式 `auto`；必需 `False`
- 限流：每主机并发 `6`；最小间隔 `700` ms
- 搜索提供器：未声明
- Access Bridge：未声明
- 域名配置：未声明
- 来源追溯：`type`=`live`；`upstreamId`=`zhswx_tw`；`upstreamFile`=空；`upstreamCommit`=空
- 正文净化规则：`0` 条
