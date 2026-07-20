# LegadoHub

一个面向小说书源插件的运行时与控制台项目。

它主要做三件事：

- 提供统一的插件运行时
- 提供可视化控制台来管理插件和官方源登录
- 提供一套适合书源适配与验证的工程骨架

如果你想把它理解得简单一点，可以把它当成：

**“书源插件宿主 + 管理控制台 + 运行时工具集”**

---

## 运行入口

- `http://<host>:8765`：Reading/Legado 与普通用户入口，只注册阅读、授权码和个人订阅 API。
- `http://<host>:8766`：管理员入口，注册管理员登录、系统控制台和管理 API。

使用 `start.bat` 或在 `backend/` 执行：

```powershell
python -m app.server --host 0.0.0.0 --public-port 8765 --admin-port 8766
```

管理员端口默认监听所有网卡。应用负责路由与身份隔离，部署方负责防火墙、反向代理、TLS 和允许访问的管理网段。

---

## 项目里有什么

### `backend/`
后端运行时。

负责：

- 插件加载
- 搜索 / 详情 / 目录 / 正文 API
- 官方源登录与状态检测
- 缓存、健康检查、搜索任务、运行调度

### `frontend/`
控制台前端。

主要用于：

- 查看插件状态
- 官方源登录
- 搜索预览与验证
- 设置与调试入口

### `plugins/`
插件目录。

这里放的是运行时可以直接加载的书源插件。

Docker 镜像只保存第三方插件种子，官方插件不进入镜像，由宿主目录 `plugins/sources/official/` 只读挂载。使用 `docker-compose.plugins.yml` 时，宿主第三方目录直接挂载到 `/app/plugins/sources/thirdparty`；目录为空时启动脚本复制镜像种子，非空时完全保留宿主内容。后端数据不映射到宿主，替换或删除容器前必须先备份。

---

## 这个仓库适合做什么

适合：

- 写和调试 LegadoHub 书源插件
- 验证插件能不能正常跑通搜索、详情、目录、正文
- 给官方源接登录壳层和状态检测

不适合：

- 堆大量专题逆向研究资产
- 存放一次性验证截图
- 作为抓包 / HAR / Frida / native 资料仓库

这个仓库更偏“运行项目”，不是“研究档案库”。

---

## 如果你要写新插件，先看哪里

建议先看：

- [Book Source Craft 说明](/C:/Home/Workspace/UGit/legado-hub/docs/skills/book-source-craft/README.md)
- [书源插件模板（中文）](/C:/Home/Workspace/UGit/legado-hub/docs/skills/book-source-craft/references/source-plugin-template.zh-CN.md)

前者告诉你这组帮助文档怎么用，后者直接给你一个最小可用插件骨架。

---

## 项目验证

安装后端和前端依赖后，在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\verify.ps1
```

该命令依次执行后端编译、依赖检查、测试、全部插件校验、前端依赖审计、lint、测试、构建和运行时导入检查，并确认真实运行数据与配置未被测试修改。

---

## 现在保留文档的原则

这个仓库只保留少量真正有用的文档：

- 项目说明
- 插件适配模板
- 插件契约 / 仓库结构说明

像下面这些东西不应该继续堆在这里：

- 归档资料
- 临时验证记录
- 逆向过程文档
- seeds / 大型参考资料包

---

## 一句话总结

**LegadoHub 是一个让书源插件“能跑、能看、能验证”的宿主项目。**
