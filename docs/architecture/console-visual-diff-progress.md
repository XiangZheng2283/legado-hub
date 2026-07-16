# `/console` 后台视觉回归进度

## 当前状态

真实路由视觉基线已建立，阶段 E 完成。

最新报告：

`frontend/visual-diff/output/2026-07-15_17-23-59-491/report.md`

## 基线定义

- 基线目录：`frontend/visual-diff/baseline/`
- 场景数量：39
- 视口：desktop 1440x900、mobile 390x844
- 角色：admin、user、anonymous
- 状态：登录/登录失败、权限回退、列表常态/空态/错误态、详情页、官方源登录、移动导航
- 旧 `untitled/` 只作为迁移历史参考，不再启动为 design server，也不再要求恢复已删除控件。

覆盖的真实页面包括：

- 登录页、管理员/用户仪表盘
- 订阅搜索结果、管理员书库、用户书库空态
- 书籍详情、章节详情
- 搜索工作台、书源管理/空态、书源详情
- 官方源常态/空态/错误态/登录弹窗
- 系统设置、移动端管理员导航

## 验证结果

- 比较像素：31,207,200
- 差异像素：0
- 像素加权整体一致率：100%
- 门禁：整体及每个场景均 >= 98%
- 结果：PASS

基线截图已抽查登录错误、书库封面、官方源、章节详情和移动端布局；截图非空，无破图和明显重叠。封面 mock 使用内嵌确定性素材，不依赖外部网络。

## 使用方式

日常回归：

```powershell
cd C:\Home\Workspace\UGit\legado-hub\frontend
node .\visual-diff\run-visual-diff.mjs
```

仅在已审核的有意 UI 变更后更新基线：

```powershell
node .\visual-diff\run-visual-diff.mjs --update-baseline
```

默认 compare 不会自动创建缺失基线；整体或任一场景一致率低于 98% 时命令失败。

## 历史参考

旧 `untitled/` 对照报告：

`frontend/visual-diff/output/2026-07-15_15-41-41-768/report.md`

该报告包含主动删除能力与路由不完整造成的差异，不再作为完成度结论。
