# 爱去小说网书源插件

## 已验证链路

| 阶段 | 入口 | 结果 |
|---|---|---|
| 搜索 | GBK 编码 `GET /search.asp?word=...` | “山野归鸿”精确命中 1 条 |
| 详情 | HTTP `GET /txt-xx/.../txt-282570.htm` | 书名、作者、状态和简介可取 |
| 下载中转 | `www.aiqu127.com/...softdownfree.asp?softid=...` | 可解析首选整本 TXT URL |
| 目录 | 首选整本 TXT | 110 个真实章节标题 |
| 正文 | TXT `Range` 请求 | 服务器返回 206；首章区间与整本原始字节完全一致 |

主站详情的 HTTPS TLS 不稳定，插件固定使用实测可用的 HTTP 主站；TXT 下载使用
`ctx.access.stealth`。目录只下载一次整本文件并记录每章字节区间，正文按 Range 拉取，
不在插件内持有缓存。

## 订阅字段

搜索和详情均返回 `tocUrl`、`lastChapter`、`bookStatus` 和整数 `chapterCount`。
当前 fixture 为“已完结 / 110 章”，订阅 payload 必须与完整目录一致。
