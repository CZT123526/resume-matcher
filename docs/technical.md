# technical.md — 技术文档

> 记录架构决策与关键设计。新人入职先读本文档 + README。

## 1. 架构分层与理由

```
frontend/ (Vite+React, 5173)         纯展示与交互，业务逻辑不下前端
    │  fetch /api/*（Vite 代理）
backend/app/
    ├── main.py        应用装配（FastAPI 实例、CORS、路由挂载）
    ├── config.py      配置中心（.env 注入，密钥不落代码）
    ├── api/           接口层：参数校验 + 调服务层 + 统一响应包裹；禁止写业务逻辑
    ├── svc/           服务层：业务逻辑 + 外部服务封装（DeepSeek/ChromaDB/模型推理）
    │                  数据访问（SQLite）也放此层，3人项目不再单拆 dao 层，避免过度设计
    └── tests/         pytest 单测；每次改动必须全绿
db/  schema.sql（唯一数据源）+ 运行期 recruiter.db（不入库）+ chroma/（向量库，不入库）
docs/ 契约与状态表（契约先行）
```

**分层理由**：api 层薄、svc 层厚——接口契约稳定（前端依赖它），业务实现可换（比如 S02 的 LLM 抽取随时可换 S06 的 BERT 抽取，Schema 一致即插即用）。

## 2. 关键设计决策

| # | 决策 | 备选项 | 选择理由 |
|---|---|---|---|
| D1 | **Monorepo 单仓双目录** | 前后端两仓 | 3人课程项目，API契约/状态表强耦合；单仓一次PR可同时改两端与文档，避免跨仓同步 |
| D2 | **SQLite 业务库 + ChromaDB 向量库** | MySQL | SQLite 零配置单文件，3人各自本地跑互不干扰，Docker打包最简；向量检索是独立需求由 ChromaDB 承担。数据量（万级）远未到 MySQL 的必要性阈值 |
| D3 | **异步任务 + 轮询**（解析/匹配） | WebSocket/SSE | 轮询实现最简单且足够（任务分钟级）；先跑通，中期有余力再升级推送 |
| D4 | **LLM 弱监督标注 + BERT 蒸馏** | 纯人工标注 | 满足课程"深度学习数据量≥1万"红线，人工只做抽检质检（详见开题报告） |
| D5 | **抽取双实现同Schema**（S02 llm / S06 bert） | 单实现 | 双模型对比是报告核心实验；服务层同Schema设计让替换零成本 |
| D6 | **DeepSeek 走 OpenAI 兼容接口 + 统一封装 S03** | 各处直调 | 重试/缓存/限流处理集中一处；换供应商只改 base_url |

## 3. 数据库设计

完整建表 SQL 见 [db/schema.sql](../db/schema.sql)（**唯一数据源**，改表先改它）。表关系：

```
jds 1──∞ match_tasks 1──∞ match_results ∞──1 resumes 1──∞ entities
                │
                └──∞ agent_logs
users（M07 预留，未启用）
```

要点：
- 6 张业务表 + 1 张预留表；所有外键 `ON DELETE CASCADE` 按需标注（resumes 删除连带 entities）
- `parse_status`/`status` 用 TEXT 存状态机值（pending/processing/done/failed），可读性优先
- 大字段隔离：`raw_text` 只在详情接口返回，列表页不查

## 4. 外部服务接入要点

### DeepSeek（LLM，OpenAI 兼容）
- 接入仅通过 `svc.S03 llm_chat()`，任何代码不得绕过它直连
- 密钥从 `settings.DEEPSEEK_API_KEY` 读取（.env 注入）；缺失时启动不报错、调用时报 E5021 并提示配置
- 超时 30s；失败重试 3 次（指数退避）；429 转 E4291；结果按 (model, messages哈希) 缓存进内存
- model id 以控制台为准，当前 `deepseek-v4.1-flash`（见 .env.example）

### ChromaDB（向量库）
- 持久化目录 `db/chroma/`（不入库）；collection：`resume_vectors`
- 写入时机：M01 解析 done 后触发向量化入库；检索侧只读

### Google Colab（训练，M02）
- 蒸馏训练脚本放 `backend/tools/`（后期），数据集目录挂载 Google Drive；产出 metrics.json 回传并更新 `GET /api/model/info`

## 5. 前端要点

- 开发期所有请求走 `/api` 前缀（Vite 代理到 8000），生产由 Nginx 做同样代理——前端代码零改动
- 统一 `request.js` 封装：解 `{code, message, data}` 包裹、统一错误弹窗
- 页面清单：上传管理页 / JD与匹配页（对话+排名卡片+证据链）/ 任务历史页
