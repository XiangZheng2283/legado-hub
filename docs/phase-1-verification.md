# Phase 1 Verification Report

## 启动步骤

1. 确保已安装 Python 3.12+。
2. 双击项目根目录下的 `start.bat`。
   - 脚本会自动创建 `.venv`（如果不存在）。
   - 自动安装 `requirements.txt` 中的依赖。
   - 启动服务前直接打印书源导入链接：
     - `http://127.0.0.1:8765/api/legado/source`
     - 当前 Windows 机器可用的局域网 IPv4 导入链接。
   - 启动 Uvicorn 服务并监听 `0.0.0.0:8765`，允许局域网设备访问。
3. 或者手动运行：
   ```powershell
   python -m pip install -r requirements.txt
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8765
   ```

## 健康检查

- URL: `http://127.0.0.1:8765/health`
- 预期返回: `{"status":"ok"}`

## 生成的聚合书源

- 文件路径: `generated/legadohub-source.json`
- 服务导入 URL: `http://127.0.0.1:8765/api/legado/source`
- 手机端阅读 APP 导入时，应使用 `start.bat` 打印的局域网 URL，而不是 `127.0.0.1`。
- `/api/legado/source` 会根据导入时使用的 Host 生成书源内部接口地址；通过局域网 URL 导入时，书源内的搜索、详情、目录、正文接口也会指向该局域网地址。
- 生成命令:
  ```powershell
  python -c "from app.core.source_generator import write_aggregate_source; print(write_aggregate_source())"
  ```
- 内容: 包含一个 Legado 书源对象的 JSON 数组，指向本地服务端点。

## 已实现的 API 端点

| 方法 | 路径 | 状态 |
|------|------|------|
| GET | `/health` | 已实现 |
| GET | `/api/info` | 已实现 |
| GET | `/api/legado/source` | 已实现 |
| GET | `/api/legado/search` | 占位 |
| GET | `/api/legado/book/{book_id}` | 占位 |
| GET | `/api/legado/book/{book_id}/toc` | 占位 |
| GET | `/api/legado/chapter/{chapter_id}` | 占位 |

## 占位端点行为

占位端点返回结构化的 JSON，包含 `"implemented": false`，例如：

```json
{
  "implemented": false,
  "items": [],
  "message": "Search parser will be implemented in phase 2"
}
```

## SQLite 数据库

- 路径: `data/app.db`
- 初始化: 服务启动时自动执行。
- 包含表: `schema_meta`, `source_registry`, `books`, `chapters`, `update_tasks`。
- 重复初始化安全（幂等）。

## 测试

运行所有测试：

```powershell
python -m pytest tests -v
```

测试文件：

- `tests/test_health.py` — 健康检查和元数据端点。
- `tests/test_legado_api.py` — 书源接口动态 Host 和占位端点结构。
- `tests/test_db.py` — 数据库初始化和表创建。
- `tests/test_source_generator.py` — 聚合书源生成和字段完整性。

## 阶段 2 待实现

- 阅读书源规则解析引擎。
- 真实搜索、书籍详情、目录、正文获取。
- 后端 Web 调试界面。
- 缓存和追更任务调度。
