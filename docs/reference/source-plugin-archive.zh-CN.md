# 第三方书源归档清单

本清单记录已从 `plugins/sources/thirdparty/` 正式运行目录移除的插件。归档只适用于域名长期失效、目标内容消失，或在 HTTP、代理与受控浏览器路径下仍无法读取的站点。

| 插件 | 最后域名 | 归档时间 | 证据 | 替代方式 |
| --- | --- | --- | --- | --- |
| `22biqu_com` | `22biqu.com` | 2026-07-28 | HTTP 裸域关闭连接；HTTPS TLS 失败；`http://www.22biqu.com/` 已变成 Namecheap 域名停放页，既有书籍 URL 返回 404。 | 由聚合搜索选择其他仍可读取同书的第三方源。 |
| `xbiquzw_net` | `xbiquzw.net` | 2026-07-30 | 原域长期出现证书不匹配、TLS 握手失败与超时；原插件实际改用 `xbiqugu.com` 镜像，与正式插件 `xbiqugu_la` 重复。 | 直接使用 `xbiqugu_la`，不再以失效域名保留重复插件 ID。 |
