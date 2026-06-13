# LegadoHub

一个面向小说书源插件的运行时与控制台项目。

它的目标很直接：

- 把不同站点的书源适配成统一插件
- 提供一套可运行、可调试、可验证的后端运行时
- 用一个控制台去管理插件、官方源登录、搜索预览和状态检查

如果你把它当成“书源插件宿主 + 调试控制台”，理解会比较准确。

---

## 这个项目解决什么问题

做书源适配时，通常会碰到这些麻烦：

- 每个站点页面结构都不一样
- 搜索、详情、目录、正文的解析逻辑很难统一
- 某些站点还会带登录、Cookie、风控、代理、分页这些额外复杂度
- 写完之后缺少一个稳定的地方去验证插件到底能不能跑

LegadoHub 做的事情，就是把这些问题拆开：

1. **插件层**只负责站点本身的适配
2. **运行时层**统一处理加载、访问、缓存、状态和验证
3. **控制台层**提供一个能看得到、点得到、调得动的管理界面

---

## 项目结构

### `backend/`
后端运行时。

这里负责：

- 加载插件
- 暴露搜索 / 详情 / 目录 / 正文 API
- 提供官方源登录与状态检测
- 做缓存、健康检查、搜索任务、运行时调度

### `frontend/`
控制台前端。

主要提供：

- 插件列表与详情
- 官方源管理
- 登录状态查看
- 搜索工作台与预览
- 设置页和验证入口

### `plugins/`
插件目录。

这里放的是运行时可以直接加载的书源插件文件。

---

## 插件长什么样

一个最小插件通常只需要：

```text
plugins/sources/example_plugin/
  metadata.yaml
  source.py
```

如果要支持更完整的维护和验证，还可以带上：

```text
plugins/sources/example_plugin/
  metadata.yaml
  source.py
  private/
  tests/
```

想看更适合直接照着写的模板，建议从这里开始：

- [书源插件模板（中文）](/C:/Home/Workspace/UGit/legado-hub/docs/skills/book-source-craft/references/source-plugin-template.zh-CN.md)

---

## 适合谁用

这个项目主要适合几类人：

### 1. 想适配新书源的人

如果你已经有目标站点，想把它做成一个可运行插件，这个仓库能提供基础运行时和验证环境。

### 2. 想维护现有书源的人

如果你已经有插件，需要做：

- 修解析
- 补目录
- 修正文
- 调登录
- 看运行状态

这个仓库会比纯脚本调试更舒服。

### 3. 想做官方源支持的人

如果你要处理：

- 登录
- Cookie
- 状态检测
- 付费章节边界

这里也已经有相应的运行时壳层和控制台界面。

---

## 开发时优先看哪里

如果你是第一次接触这个项目，推荐顺序：

1. 先看根目录结构和 `backend/`、`frontend/`、`plugins/`
2. 再看插件模板：
   - [book-source-craft README](/C:/Home/Workspace/UGit/legado-hub/docs/skills/book-source-craft/README.md)
   - [书源插件模板（中文）](/C:/Home/Workspace/UGit/legado-hub/docs/skills/book-source-craft/references/source-plugin-template.zh-CN.md)
3. 如果要理解插件契约，再看：
   - [source-plugin-contract.zh-CN.md](/C:/Home/Workspace/UGit/legado-hub/docs/architecture/source-plugin-contract.zh-CN.md)

---

## 这个仓库更适合保留什么

更适合保留：

- 可运行源码
- 插件适配模板
- 必要的架构说明
- 控制台与运行时代码

不适合长期堆积：

- 大量一次性验证记录
- 临时调试脚本
- 逆向抓包产物
- 重型参考资料包
- 与运行无关的专题研究资产

也就是说，这里更像是一个**运行项目**，而不是一个**资料仓库**。

---

## 一句话总结

**LegadoHub 是一个把书源插件“跑起来、看起来、验证起来”的宿主项目。**
**ps gpt写东西就是不当人话**