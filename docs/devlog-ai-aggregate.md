# AI 聚合源后端开发日志

## Phase 1 — 基础框架搭建（Codex 完成）

已有骨架：
- `aggregate_settings.py` / `aggregate_reviews.py` / `aggregate_processor.py`
- `backend/app/ai/` 模块（`__init__.py` / `request_builder.py` / `compat.py` / `models_catalog.py` / `client.py` stub）
- `db.py` schema + `ensure_current_schema()` 增量补列
- Console API 聚合设置 / 聚合书架 / 章节列表 / 评论接口骨架
- 14 个定向测试通过

## Phase 2 — Bug 修复与模块补全

### 新增文件（10 个）
| 文件 | 说明 |
|------|------|
| `backend/app/ai/client.py` | **重写** — httpx 异步客户端，`chat()` / `list_models()` / `test_connectivity()` |
| `backend/app/ai/lexicon.py` | 敏感词 Trie 扫描器，支持 `*`/`□`/`x`/空格掩码检测 + `from_path()` 目录加载 |
| `backend/app/services/aggregate_alignment.py` | 章节正文分类（full/preview/empty）+ 跨源对齐（标题相似 + 滑动窗口 preview 匹配）+ alignment JSON 构建 |
| `backend/app/services/aggregate_ai_service.py` | AI 聚合服务骨架：`process_official_full` / `process_with_candidates` / `process_third_party_primary` |
| `backend/tests/test_ai_client.py` | 17 个 AI 客户端测试 |
| `backend/tests/test_lexicon.py` | 16 个敏感词扫描测试 |
| `backend/tests/test_retry_logic.py` | 19 个重试/退避/错误码测试 |
| `backend/tests/test_aggregate_alignment.py` | 17 个章节对齐测试 |
| `backend/tests/test_aggregate_ai_service.py` | 7 个 AI 服务测试 |
| `backend/tests/test_aggregate_processor_state_machine.py` | 5 个状态机测试 |

### 修改文件（6 个）
| 文件 | 改动 |
|------|------|
| `backend/app/services/aggregate_processor.py` | 新增错误码分类 / 退避计算 / `_chapters_for_processing` 排除终态章节 / `_process_chapter` 状态机重写 / `ai_service` 依赖注入 / fallback 响应 |
| `backend/app/services/aggregate_settings.py` | `_looks_masked()` 防止脱敏 key 覆盖真实 key |
| `backend/app/api/console.py` | `test_provider` / `fetch_models` 接入真实 AI 客户端；修复 `get_aggregate_chapter` JOIN 列歧义 |
| `backend/app/services/aggregate_reviews.py` | 新增 `hot_review_bubble_label()` — 固定 "热评 N" |
| `backend/app/ai/client.py` | 新增 `_require_auth_config()` — `list_models` 只需 baseUrl+apiKey |
| `backend/tests/test_aggregate_processor.py` | 新增 fallback / alignment JSON / 窗口测试 + monkeypatch 修复 |

### 已修复的 Bug
1. 终态章节无限重入队列（`AI_BAD_REQUEST` / `retry_count >= 5`）
2. `list_models` 要求 model 已配置
3. 脱敏 API key 覆盖真实 key
4. 敏感词扫描空格误报
5. 词库目录加载支持
6. VIP 预览直接标记 processed → 改为走候选对齐 + AI + fallback 状态机
7. 第三方主源被硬当 official → 改为走 AI 归属校验
8. Fallback 章节阅读接口返回占位 → 改为返回 fallback 正文

### 测试总数
103 个测试全部通过（Phase 1 的 14 个 + Phase 2 新增 89 个）

## Phase 3 — 状态机 P1 修复（当前）

### 核心改动
`_process_chapter` 从「全走 processed」改为四路径状态机：

```
                    ┌─ official full → processed (selectedContentSource=official)
                    │
_fetch chapter ─────┼─ preview → 候选对齐 → AI → processed
                    │                      ├─ AI fail → fallback (候选正文)
                    │                      └─ 无候选 → fallback (预览正文)
                    │
                    └─ third-party full → AI 归属校验 → processed
                                           └─ AI fail → fallback + 降级标记
```

### 新增依赖注入
- `AggregateProcessor.__init__(..., ai_service=None)`
- 测试可传 `_FakeAIService`，避免真实 provider

### 新增 helper 方法
- `_load_aggregate_payload()` — 从 DB 读候选源列表
- `_is_official_source()` — 查 PluginLoader 判断是否官方
- `_candidate_sources_from_payload()` — 提取非主源候选
- `_write_chapter_result()` — 统一写入 processed/fallback 结果
- `_handle_processing_error()` — 错误处理 + 重试退避

### aggregate_chapter_response 修复
- `status == 'processed'` → `status in ('processed', 'fallback')`
- fallback 章节也触发 `_write_processed_chapter_if_needed` 写本地 md

---

*以下为下一阶段 TODO，尚未实现：*

## Phase 3.5 — 补全连接层

### 改动

| 文件 | 改动 |
|------|------|
| `backend/app/services/aggregate_ai_service.py` | `__init__` 增加 `lexicon` 可选参数；新增 `_scan_blocked_words()` 方法；`process_with_candidates` / `process_third_party_primary` prompt 中自动追加敏感词候选 |
| `backend/app/services/aggregate_processor.py` | `_process_preview_chapter` 候选查找从 naive URL 拼接改为 `catalog.toc(cand_book_id)` + 按 index 匹配真实章节 |
| `backend/tests/test_aggregate_processor_state_machine.py` | `_FakeCatalog` 增加 `toc()` 方法；新增 2 个 `_is_official_source` 测试 |
| `backend/tests/test_aggregate_processor.py` | `FakeCatalog` 增加 `toc()` 方法 |
| `backend/tests/test_aggregate_ai_service.py` | 新增 2 个 lexicon 集成测试 |

### 新增测试（4 个）
| 测试 | 验证 |
|------|------|
| `test_lexicon_candidates_appended_to_prompt` | 有 lexicon + 掩码正文 → prompt 包含 "疑似被屏蔽" + 候选词 |
| `test_no_lexicon_no_blocked_word_section` | 无 lexicon → prompt 不含敏感词段 |
| `test_is_official_source_returns_false_for_unknown` | 未知 source_id → False |
| `test_is_official_source_returns_true_for_official` | 真实官方源 → True；非官方 → False |

### 测试总数
107 个全部通过

## Phase 4 — TOC 缓存 + 前文校准 + 偏差值

### 改动

| 文件 | 改动 |
|------|------|
| `backend/app/services/aggregate_processor.py` | `__init__` 增加 `_toc_cache`；新增 `_cached_toc()` / `_clear_toc_cache()` / `_load_previous_chapters_context()`；`run_book_task` 开始时清缓存；`_process_preview_chapter` 用 `_cached_toc` 替代直接 `catalog.toc`；`_process_preview_chapter` / `_process_third_party_primary` 传入 `previous_context` |
| `backend/app/services/aggregate_ai_service.py` | `process_with_candidates` / `process_third_party_primary` 新增 `previous_context` 参数；prompt 中插入 `--- 前文参考 ---` 段 |
| `backend/app/services/aggregate_alignment.py` | 新增 `compute_deviation_score(original, ai_output)` — 基于 LCS 的字符级相似度 |
| `backend/tests/test_aggregate_alignment.py` | 新增 4 个偏差值测试 |
| `backend/tests/test_aggregate_ai_service.py` | 新增 1 个前文上下文 prompt 测试 |
| `backend/tests/test_aggregate_processor_state_machine.py` | 新增 4 个测试（TOC 缓存 / 前文上下文加载 / AI 服务接收前文上下文） |

### 新增测试（9 个）
| 测试 | 验证 |
|------|------|
| `test_deviation_score_identical_text` | 相同文本 → ≥ 0.95 |
| `test_deviation_score_similar_text` | 轻微修改 → 0.70–0.99 |
| `test_deviation_score_completely_different` | 完全不同 → < 0.30 |
| `test_deviation_score_empty_input` | 空输入 → 0.0 |
| `test_previous_context_included_in_prompt` | 传入 previous_context → prompt 包含 "前文参考" |
| `test_toc_cache_avoids_repeated_calls` | 同一 book_id 只调一次 toc() |
| `test_toc_cache_cleared_between_books` | `_clear_toc_cache()` 清空缓存 |
| `test_load_previous_chapters_context` | 返回前 N 章已处理内容摘要 |
| `test_previous_context_passed_to_ai_service` | 前文存在时 AI service 收到 previous_context |

### 测试总数
117 个全部通过

## Phase 5 — 偏差值接入 + autojunk 修复

### 改动

| 文件 | 改动 |
|------|------|
| `backend/app/services/aggregate_processor.py` | `_write_chapter_result` 新增 `deviation_score` / `ai_prompt_tokens` / `ai_completion_tokens` / `ai_total_tokens` / `ai_latency_ms` 参数；preview/第三方路径 AI 输出后计算偏差值，低于 `deviationThreshold` 时拒绝写 processed 并 fallback；`classify_error` 新增 `AI_OUTPUT_DEVIATION` |
| `backend/app/services/aggregate_alignment.py` | 所有 `SequenceMatcher` 调用加入 `autojunk=False`，修复长中文文本重复字符导致 ratio=0.0 的严重 bug |
| `backend/tests/test_aggregate_processor_state_machine.py` | 新增 3 个偏差值测试 |

### 新增测试（3 个）
| 测试 | 验证 |
|------|------|
| `test_high_deviation_reverts_to_fallback` | AI 输出偏离过大 → status='fallback'，正文是候选源而非坏 AI 输出 |
| `test_low_deviation_keeps_processed` | AI 输出与候选相似 → status='processed'，deviation_score > 0 已写入 |
| `test_ai_output_deviation_error_code` | `AI_OUTPUT_DEVIATION` 错误码正确分类 |

### 关键修复
`SequenceMatcher(autojunk=True)` 对长中文重复文本会将高频字符标为 junk，导致 ratio=0.0。
改为 `autojunk=False` 后相似度计算恢复正常。

### 测试总数
120 个全部通过

## Phase 6 — 主源优先级 + API Key 加密 + 模型目录扩充

### 改动

| 文件 | 改动 |
|------|------|
| `backend/app/services/aggregate_settings.py` | `DEFAULT_CONTENT_WORKFLOW` 新增 `primarySourcePriority: ["qidian_com_web"]`；`ai_provider_config()` 读取时自动解密；`save_settings()` 写入时自动加密 |
| `backend/app/services/aggregate_virtual_source.py` | `primary_book_id_from_payload()` 新增 `source_priority` 参数，优先按用户配置顺序匹配主源，无匹配再走官方优先 + 评分逻辑 |
| `backend/app/services/aggregate_processor.py` | `enqueue_book()` 从 settings 读取 `primarySourcePriority` 传入 `primary_book_id_from_payload` |
| `backend/app/ai/encryption.py` | **新增** — Fernet 对称加密，`encrypt_api_key()` / `decrypt_api_key()` / `is_encrypted()`；密钥从 `LEGADOHUB_AI_ENCRYPTION_KEY` 环境变量或自动生成的 `data/.ai_encryption_key` 文件读取 |
| `backend/app/ai/models_catalog.py` | 从 3 个模型扩充到 30+ 个，覆盖 DeepSeek / OpenAI / Anthropic / Moonshot / Qwen / GLM / MiniMax / Mistral / SiliconFlow |
| `backend/tests/test_aggregate_processor.py` | 新增 3 个主源优先级测试 |
| `backend/tests/test_aggregate_settings.py` | 新增 2 个加密测试（密文存储 + 旧明文可读） |

### 新增测试（5 个）
| 测试 | 验证 |
|------|------|
| `test_primary_book_id_respects_source_priority` | 按优先级选择主源 |
| `test_primary_book_id_priority_falls_back_to_next` | 优先源不在 payload 时尝试下一个 |
| `test_primary_book_id_priority_empty_falls_back_to_default` | 空优先级列表走默认逻辑 |
| `test_api_key_encrypted_at_rest` | DB 中存密文，API 返回明文 |
| `test_legacy_plaintext_key_still_readable` | 旧明文 key 不被破坏，仍可读取 |

### 测试总数
125 个全部通过

---

### 下一阶段 TODO（未实现）

1. **起点热评真实抓取**：`aggregate_reviews.py` normalize 框架已完成，实际 HTTP 抓取待实现。
2. **目录同步与断更恢复**：plan §8.6 标题/索引变更、消失章节处理。
3. **候选章节 TOC 分页/容错**：当前只取 TOC 第一页，候选源章节数量大时可能漏匹配。
4. **前端 UI 构建**：
   - 聚合设置页：AI Provider 配置 + 测试连通 + 拉模型下拉 + 主源优先级拖拽排序
   - 聚合书架页：书籍列表 + 分页 + 状态筛选 + 进度条 + 操作按钮
   - 聚合书详情页：章节列表 + 状态标签 + 偏差值 + 重试
   - 章节详情页：正文预览 + alignment 信息 + fallback 来源 + 热评
