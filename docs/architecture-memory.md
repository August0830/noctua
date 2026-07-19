# 本地存储架构

## 问题

OpenCode 的 EverMe MCP 插件（`@everme/memory-mcp`）设计为连接 **EverMe 云服务**（`api.everme.evermind.ai`），
但它可以通过 `EVERME_API_BASE` 环境变量指向任意 API 端点。

本地自建的 EverOS 引擎提供核心记忆功能（`/api/v1/memory/add`、`/api/v1/memory/search` 等），
但 **API 路径和请求/响应格式** 与 MCP 插件预期的 EverMe Cloud Gateway 不一致。

## 解决方案

`gateway_compat.py` 是 **EverMe Cloud Gateway 的本地最小兼容层**，运行在 EverOS FastAPI 应用内。

```
┌─────────────────────────────────────────────────────────────┐
│ OpenCode                                                     │
│   MCP 插件 (agent-sdk) → 认为自己在和云 Gateway 对话           │
│   POST /api/v1/mem/personal  {"conversationId": "...", ...}  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ gateway_compat.py  ← EverOS 进程内，FastAPI 路由             │
│                                                              │
│ 职责：                                                       │
│   1. 路径兼容 — /api/v1/mem/* → /api/v1/memory/*            │
│   2. 格式翻译 — conversationId → session_id                  │
│   3. 响应封装 — EverOS 响应 → Gateway 风格 {"status":0,...}  │
│   4. 跳过鉴权 — 本地信任，不校验 evt_* token                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ EverOS Engine（零修改）                                       │
│   /api/v1/memory/add    → memorize service                  │
│   /api/v1/memory/search → search service                    │
│   /api/v1/memory/get    → get service                       │
│   /api/v1/memory/flush  → force boundary detection          │
└──────────────────────────────────────────────────────────────┘
```

## 注入方式

`run_everos.py` 在 uvicorn 导入 `create_app` 之前，用猴子补丁替换它：

```python
# 1. 引入原始 create_app
from everos.entrypoints.api.app import create_app as _original

# 2. 定义增强版
def create_app(**kwargs):
    app = _original(**kwargs)
    app.include_router(gw_router)  # ← 注入兼容路由
    return app

# 3. 替换模块引用（uvicorn 后续 import 时获取的是增强版）
everos.entrypoints.api.app.create_app = create_app
```

## 关键设计决策

| 决策 | 理由 |
|------|------|
| 兼容路由放在 EverOS 进程内而非独立进程 | 零网络开销，直接函数调用 |
| 猴子补丁而非 fork EverOS | EverOS 可独立升级，兼容层不受影响 |
| 不实现完整 Gateway（鉴权/计费/多租户） | 本地单用户场景不需要 |

## 文件位置

```
noctua/scripts/
├── gateway_compat.py  ← 兼容路由定义（如果 Gateway 协议变只改这个）
├── run_everos.py      ← 启动入口 + 猴子补丁
└── import_opencode_sessions.py  ← 历史数据批量导入
```

## 记忆保存时机

EverMe MCP 插件不是每句话都存，而是按触发条件**选择性保存**：

| 触发条件 | 工具 | 示例 |
|----------|------|------|
| Session 启动 | `mem_context` | 自动拉取用户画像和历史记忆上下文 |
| 用户说出偏好/事实/决策 | `mem_save_fact` | "我喜欢本地部署而非云服务" |
| 解决了值得复用的任务 | `mem_save_turn` | 完整的技术决策轨迹 |
| 用户提到之前的讨论 | `mem_search` | 语义检索历史记忆 |

当前选择性保存适合**人机协作**场景，但不适合**自演进 Agent**（需要全量轨迹用于 LoRA 训练）。
Phase 3 将实现 Agent 轨迹的自动全量保存。

## 存储增长估算

当前 250 sessions（约 9,700 条消息）的存储分布：

```
~/.everos/
├── .index/lancedb/     233M  ← 向量索引（73%），语义搜索用
├── .index/sqlite/       74M  ← 结构化索引（23%），状态/元数据
├── opencode/noctua/     11M  ← Markdown 原文（3%），事实来源
└── 其他                  0M
  总计                  318M  (~1.3M/session)
```

增长分析：

| 数据量 | 预估占用 | 说明 |
|--------|---------|------|
| 每天 5 session | +6.5M/天 | 正常工作节奏 |
| 每天 20 session | +26M/天 | 高强度开发 |
| 月均（5/天） | ~200M/月 | |
| 年均（5/天） | ~2.4G/年 | |

安全边际（假设 20G 可用空间）：

| 场景 | 可运行时间 |
|------|-----------|
| 每天 5 session | ~8 年 |
| 每天 20 session | ~2 年 |
| 每天 50 session（含 Agent 自动轨迹） | ~10 个月 |

**压缩因素：** cascade 的 episode 聚类合并会定期收缩 LanceDB 索引；
Markdown 原文（11M/250 sessions）是最稳定的存量，增长极慢。

### 监控命令

```bash
# 总占用
du -sh ~/.everos/

# 分项
du -sh ~/.everos/.index/lancedb ~/.everos/.index/sqlite ~/.everos/opencode
```

## Session 捕获策略（双通道）

```
通道 A：实时（MCP 插件，模型驱动）
  → mem_save_fact（偏好/决策）
  → mem_save_turn（关键任务轨迹）
  → 优点：即时可用
  → 缺点：依赖模型主动调用，覆盖面不稳定

通道 B：定期（导入脚本，Pull 模式）
  → import_opencode_sessions.py（checkpoint 跳过已有）
  → 建议：每天/每会话结束时跑一次
  → 优点：100% 覆盖，不重不漏
  → 缺点：有延迟（需 cascade 提取后才能检索）
```

推荐工作流：

```bash
# 下班前跑一次，补录今天所有 session
cd /Users/mengzhilu.mzl/Desktop/working/noctua
source .venv/bin/activate
python3 scripts/import_opencode_sessions.py
```

## 参考

- EverMe Cloud Gateway 协议：`@everme/agent-sdk` 源码中的 `client.js`、`search.js`、`personal-memory.js`
- EverOS API 参考：`everos/entrypoints/api/routes/*.py`
