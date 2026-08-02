# 第三方书源限流校对

## 范围

本文记录归档前 30 个第三方插件的实网并发校对；当前正式运行目录为 29 个。插件清单和当前声明另见
[`source-plugin-catalog.zh-CN.md`](source-plugin-catalog.zh-CN.md)。限流由宿主调度器执行：
`perHostConcurrency` 限制同一插件的同时生命周期调用，`minIntervalMs` 限制相邻调用的起始间隔。

下方历史表中的“限制”保留 2026-07-27 至 2026-07-28 的首轮结果，不代表当前运行配置。当前 beta 运行策略为：

- 普通 HTTP 源：单书单源并发 3、插件全局并发 6。
- Browser 源、官方源和容量仅验证到 3 或未评估的源：单书单源并发 1、各自全局并发 3。
- `minIntervalMs` 继续限制请求启动频率；提高并发只增加等待响应时的并行量。
- 容量探针稳定到 6 或 12 的普通 HTTP 源才使用全局并发 6；探针峰值不直接作为生产值。

官方源不在本表中，官方插件仍在 QDFCCKK 仓库维护。
已移出正式目录的站点见 [`source-plugin-archive.zh-CN.md`](source-plugin-archive.zh-CN.md)。

## 可用性结论

- **真实闭环通过**：`0xs_net`、`69shuba_com`、`69shuba_tw`、`96dushu_com`、`dongtanxs_com`、`hjwzw_com`、`mingzw_tw`、`quanben5_com`、`shuhaige_net`、`shumilou_co`、`shumilou_top`、`sto_com`、`sudugu_org`、`ttkan_co`、`uuread_tw`、`xiaoshuohu_com`、`zhswx_tw`。`biquge365_net` 虽闭环通过，但当次命中只有 4 章的同名书，不能作为完整目录证据。
- **条件可用**：`0xs_net`、`69shuba_com`、`69shuba_tw`、`96dushu_com`、`kks101_com`、`ttkan_co`、`twkan_com`。这些源依赖浏览器上下文、配置代理或短期会话；缺少运行时前提或遭遇动态挑战时，不判定为插件失效。
- **已归档**：`xbiqugu_la` 在 `.com`、`.la` 和旧 `.net` 重定向链路上均无法建立有效读取，已从正式运行目录移除。

## 证据等级

- **实测**：2026-07-27 三本书、每书最多 20 章的低样本审计，随后以 2、3 并发探针确认。
- **挑战保护**：浏览器、Cloudflare 或强制代理源。历史证据只支持单并发，不将一次成功当作可提高的依据。
- **保守基线**：没有可靠容量样本，或近期存在超时、空搜索、网络错误。历史证据只支持单并发；数字不是站点承诺。

## 2026-07-30 容量复测

本轮对每个普通 HTTP 源按 `1 / 3 / 6 / 12` 逐级进行两轮短时突发，档位间冷却 3 秒；Browser 源受浏览器池约束，只测 `1 / 3`。进入容量测试的章节必须先通过顺序读取且正文不少于 120 字，避免短章节被误判为并发失败。正常运行仍保留 metadata 中的 `minIntervalMs`。

| 结论 | 插件 | 运行配置 |
| --- | --- | --- |
| 稳定到 12 | `hjwzw_com`、`lingdiankanshu_com`、`mingzw_tw`、`qianyezw_com`、`quexs_org`、`shumilou_top`、`sto_com`、`uuread_tw`、`xiaoshuohu_com`、`yeban360_com`、`zhswx_tw` | 普通 HTTP：全局 6、单书 3 |
| 稳定到 6 | `biquge365_net`、`dongtanxs_com`、`quanben5_com`、`ttkan_co` | 普通 HTTP：全局 6、单书 3 |
| 稳定到 3 | `czbooks_net`、`sudugu_org` | 保守：全局 3、单书 1 |
| Browser 稳定到 3 | `69shuba_tw`、`ixdzs8_com` | Browser：全局 3、单书 1 |
| 本环境未评估 | `0xs_net`、`69shuba_com`、`96dushu_com`、`dxtxt_cc`、`kks101_com`、`qiexs_cc`、`shuhaige_net`、`shumilou_co`、`suixkan_com`、`twkan_com` | 保持全局 3、单书 1；不推断站点上限 |

关键边界：`dongtanxs_com` 在 12 档出现 HTTP 429；`ttkan_co` 在 12 档第二轮出现 HTTP 503；`czbooks_net` 和 `sudugu_org` 在 6 档失败。`twkan_com` 本轮检测到挑战页。未评估表示没有得到可用于容量测试的合格正文，不等于插件永久不可用。

| 插件 | 限制 | 证据 | 说明 |
| --- | --- | --- | --- |
| `69shuba_com` | 1 / 1200ms | 实测 | 2、3 并发均出现 429。 |
| `biquge365_net` | 2 / 600ms | 实测 | 3 并发成功；目录数据质量仍需由聚合校验。 |
| `dongtanxs_com` | 2 / 600ms | 实测 | 3 并发成功。 |
| `hjwzw_com` | 2 / 600ms | 实测 | 3 并发成功。 |
| `mingzw_tw` | 2 / 700ms | 实测 | 3 并发成功。 |
| `quanben5_com` | 1 / 900ms | 实测 | 2 并发成功，3 并发中 1 个正文请求超时。 |
| `shumilou_top` | 2 / 800ms | 实测 | 3 并发成功，保留更大间隔。 |
| `sto_com` | 2 / 700ms | 实测 | 3 并发成功。 |
| `ttkan_co` | 2 / 600ms | 实测 | 3 并发成功。 |
| `uuread_tw` | 1 / 900ms | 实测 | 2 并发成功，3 并发已有运行错误，留出余量。 |
| `zhswx_tw` | 2 / 700ms | 实测 | 3 并发成功。 |
| `69shuba_tw` | 1 / 1200ms | 挑战保护 | 必须代理；首次由 Browser 建立 Aegis 会话，后续复用 Cookie 走 Stealth HTTP。 |
| `kks101_com` | 1 / 1200ms | 挑战保护 | 可选浏览器和强制代理。 |
| `twkan_com` | 1 / 1000ms | 挑战保护 | 直连优先；强制代理会触发挑战，失败后才允许宿主自动回退代理。 |
| `0xs_net` | 1 / 1000ms | 挑战保护 | 2026-07-31 桌面站闭环通过：搜索 20 条、目录 848 章、正文 3722 字；伪 200 错误页或 403 时需浏览器会话。 |
| `96dushu_com` | 1 / 900ms | 挑战保护 | 2026-07-31 搜索提供器与宿主 Chrome 指纹链路闭环通过：搜索 7 条、目录 493 章、正文 2855 字。 |
| `shuhaige_net` | 1 / 1200ms | 保守基线 | 2026-07-27 宿主调用超时（约 8.0 秒）。 |
| `shumilou_co` | 1 / 1200ms | 保守基线 | 2026-07-28 现场搜索返回 HTTP 403，读取链路未评估。 |
| `sudugu_org` | 1 / 1200ms | 保守基线 | 2026-07-31 `.org` 主域闭环通过：搜索 6 条、目录 810 章、正文 3637 字；`.co` 仅作搜索、详情和目录备用。 |
| `xiaoshuohu_com` | 1 / 1000ms | 实测 | 2026-07-28 全链路通过：搜索 1 条、目录 788 章、正文 3511 字。 |

## 最近复测

- `sudugu_org`：`.org` 保持主域并完成实网闭环；`.co` 提供独立备用搜索协议，但部分旧书正文容器为空，因此不替代主域正文链路。
- `96dushu_com`：普通 `requests` 仍可能遇到 Cloudflare Managed Challenge；宿主 Chrome 指纹、共享 CF 会话和浏览器回退链路已实测完成搜索、详情、目录和正文。
- `0xs_net`：改用桌面站搜索、详情、完整目录和正文链路；宿主模拟 Chrome 响应会持久化 `Set-Cookie`，避免详情成功后目录仍被拒绝。
- `69hsw_com`、`ranwen8_cc`、`tianxibook_com`、`xhytd_com`、`xbiqugu_la` 已按维护决策从正式插件目录移除，历史探测证据保留在归档清单和采样报告中。

## 调整规则

提高某个源的并发前，必须在低频条件下完成至少三本书、每书 20 章的读取，并在目标值及目标值加 1 的并发下重复验证。任一轮出现 403、429、挑战页、连接重置、空目录或正文异常，即降低到上一档并保留证据。

不得由插件自行重试、排队或绕过挑战。代理回退、总并发、超时和退避始终由宿主运行时负责。
