# backend-api.md — API 契约（唯一准绳）

> **改接口必须先改本文档再改代码**；前后端联调以本文档为准。
> 实现进度见 [status/api.md](status/api.md)。

## 通用约定

- Base URL：`http://127.0.0.1:8000`；前端经 Vite 代理以 `/api`、`/health` 访问
- 登录：当前版本全部接口**不需要登录**（M07 预留 `/api/auth/*`，届时补"是否需要登录"标注）
- 成功响应统一包裹：`{"code": 0, "message": "ok", "data": {...}}`
- 失败响应：HTTP 状态码 + `{"code": "E####", "message": "错误说明", "data": null}`

### 错误码表

| HTTP | code | 含义 | 触发场景示例 |
|---|---|---|---|
| 400 | E4001 | 参数错误 | 缺少必填字段、top_k 超范围 |
| 400 | E4002 | 文件类型不支持 | 上传 .exe / 空文件 |
| 404 | E4041 | 资源不存在 | resume_id / task_id 无效 |
| 409 | E4091 | 状态冲突 | 任务运行中重复发起 |
| 413 | E4131 | 文件过大 | 简历 > 10MB |
| 429 | E4291 | 上游LLM限流 | DeepSeek 429 |
| 500 | E5001 | 服务内部错误 | 未捕获异常 |
| 502 | E5021 | LLM服务不可用 | DeepSeek 连接失败/超时 |

---

## 0. 健康检查

### GET /health ｜无需登录 ｜✅ 已实现
- 响应：`{"status": "ok"}`

---

## 1. 简历模块（M01）

### POST /api/resumes/upload ｜无需登录
上传简历，后台异步解析（LLM结构化抽取），返回 resume_id 供轮询。
- 请求：`multipart/form-data`，字段 `file`（PDF/DOCX，≤10MB）
- 响应 `202`：
```json
{"code": 0, "message": "ok", "data": {"resume_id": 1, "file_name": "张三.pdf", "parse_status": "pending"}}
```

### GET /api/resumes ｜无需登录
- Query：`page=1`、`page_size=20`、`parse_status=pending|processing|done|failed`（可省）
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {"total": 2, "items": [
  {"resume_id": 1, "file_name": "张三.pdf", "parse_status": "done", "created_at": "2026-10-10 15:00:00"}
]}}
```

### GET /api/resumes/{id} ｜无需登录
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {
  "resume_id": 1, "file_name": "张三.pdf", "parse_status": "done",
  "raw_text": "（前500字预览……）",
  "entities": [
    {"field_key": "name", "field_value": "张三", "source": "llm"},
    {"field_key": "degree", "field_value": "本科", "source": "llm"},
    {"field_key": "skill", "field_value": "Python", "source": "llm"}
  ],
  "created_at": "2026-10-10 15:00:00"
}}
```

### DELETE /api/resumes/{id} ｜无需登录 ｜P1
- 响应 `200`：`{"code": 0, "message": "ok", "data": {"resume_id": 1, "deleted": true}}`

---

## 2. 岗位 JD 模块（M03）

### POST /api/jds ｜无需登录
- 请求体：
```json
{"title": "Python后端工程师", "content": "负责后端服务开发。要求：3年Python经验，熟悉FastAPI，本科及以上。"}
```
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {"jd_id": 1, "title": "Python后端工程师"}}
```
> 说明：`content` 原文入库；由 LLM 抽取的结构化要求（学历/年限/技能列表）写入 `req_json`，前端无需提交。

### GET /api/jds ｜无需登录
- 响应 `200`：`{"code": 0, "message": "ok", "data": {"items": [{"jd_id": 1, "title": "Python后端工程师", "created_at": "..."}]}}`

### GET /api/jds/{id} ｜无需登录
- 响应 `200`：含 `content` 与 `req_json`（结构化要求对象）

---

## 3. 匹配任务模块（M03 核心）

### POST /api/match-tasks ｜无需登录
- 请求体：
```json
{"jd_id": 1, "top_k": 10}
```
- 响应 `202`：
```json
{"code": 0, "message": "ok", "data": {"task_id": 1, "status": "pending"}}
```

### GET /api/match-tasks/{id} ｜无需登录
轮询任务状态（前端 2s 间隔）。
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {"task_id": 1, "status": "running", "progress": 60, "error": null}}
```
> status：`pending → running → done | failed`；progress 为 0–100

### GET /api/match-tasks/{id}/results ｜无需登录
- 响应 `200`（任务 done 后有效）：
```json
{"code": 0, "message": "ok", "data": {"task_id": 1, "jd_title": "Python后端工程师", "items": [
  {"rank": 1, "resume_id": 1, "candidate_name": "张三", "score": 92.5,
   "evidence": ["3年Python后端经验 ✓", "熟悉FastAPI ✓", "本科学历 ✓"]}
]}}
```

---

## 4. 对话模块（M03/M04，调度Agent入口）

### POST /api/chat ｜无需登录
HR 自然语言指令入口（如"帮我找出会Python的人"）。
- 请求体：
```json
{"message": "帮我找出会Python的后端", "task_id": null}
```
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {
  "reply": "已为你检索到 8 位候选人，其中 3 位匹配 Python 后端要求，是否发起完整匹配？",
  "intent": "search_candidates",
  "agent_trace": [{"agent": "调度Agent", "step": "意图理解", "detail": "识别为候选人检索"}]
}}
```

---

## 5. 报告模块（M05）｜P1

### GET /api/reports/{task_id}/export ｜无需登录
- 响应：`200`，`Content-Type: application/pdf`，文件流（评估报告，含排名、证据链、模型指标）

---

## 6. 模型管理模块（M02）

### GET /api/model/info ｜无需登录 ｜P1
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {"model_name": "bert-base-chinese-ner-distill", "version": "v0.1", "f1": 0.71, "train_samples": 10240, "updated_at": "..."}}
```

### POST /api/admin/distill ｜无需登录 ｜P1
触发"LLM自动标注 → 蒸馏训练"流水线（异步）。
- 响应 `202`：`{"code": 0, "message": "ok", "data": {"job_id": "distill-20261010", "status": "started"}}`
