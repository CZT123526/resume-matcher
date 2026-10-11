# backend-api.md — API 契约（唯一准绳）

> **改接口必须先改本文档再改代码**；前后端联调以本文档为准。
> 每个字段的类型/约束/示例见 [api-schemas.md](api-schemas.md)（代码契约：`backend/app/schemas/`）。
> 架构约定：**运行时零外部 API 依赖**，全部推理由本地 BERT 完成；DeepSeek 仅存在于离线评测脚本（不提供 HTTP 接口）。
> 实现进度见 [status/api.md](status/api.md)。

## 通用约定

- Base URL：`http://127.0.0.1:8000`；前端经 Vite 代理以 `/api` 前缀访问
- 登录：当前版本全部接口**不需要登录**（users 表预留）
- 成功响应统一包裹：`{"code": 0, "message": "ok", "data": {...}}`
- 失败响应：HTTP 状态码 + `{"code": "E####", "message": "错误说明", "data": null}`；参数错误时 message 附带字段明细
- 时间格式：统一 ISO 8601（`T` 分隔），如 `2026-10-10T15:00:00`

### 错误码表

| HTTP | code | 含义 | 触发场景示例 |
|---|---|---|---|
| 400 | E4001 | 参数错误 | 缺少必填字段、top_k 超范围 |
| 400 | E4002 | 文件类型不支持 | 上传 .exe / 空文件 |
| 404 | E4041 | 资源不存在 | resume_id / task_id 无效 |
| 409 | E4091 | 状态冲突 | 任务运行中重复发起 |
| 413 | E4131 | 文件过大 | 简历 > 10MB |
| 500 | E5001 | 服务内部错误 | 未捕获异常 |

---

## 0. 健康检查

### GET /health ｜无需登录 ｜✅ 已实现
- 直连探活；`GET /api/health` 为代理路径别名（前端统一走 `/api` 前缀）
- 响应：`{"status": "ok"}`

---

## 1. 简历模块（M01）

### POST /api/resumes/upload ｜无需登录
上传简历，后台异步解析（BERT NER 抽取），返回 resume_id 供轮询。
- 请求：`multipart/form-data`，字段 `file`（PDF/DOCX，≤10MB）；批量上传由前端多选后逐份调用本接口
- 原件同步保存至服务端 `db/uploads/{resume_id}.{ext}`（不入 git），供下方 `GET /{id}/file` 查看；删除简历时原件一并清理
- 响应 `202`：
```json
{"code": 0, "message": "ok", "data": {"resume_id": 1, "file_name": "张三.pdf", "parse_status": "pending"}}
```

### GET /api/resumes ｜无需登录
- Query：`page=1`、`page_size=20`、`parse_status=pending|processing|done|failed`（可省）
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {"total": 2, "items": [
  {"resume_id": 1, "file_name": "张三.pdf", "parse_status": "done", "created_at": "2026-10-10T15:00:00"}
]}}
```

### GET /api/resumes/{id} ｜无需登录
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {
  "resume_id": 1, "file_name": "张三.pdf", "parse_status": "done", "parse_error": null,
  "raw_text": "（前500字预览……）",
  "entities": [
    {"field_key": "name", "field_value": "张三", "source": "bert"},
    {"field_key": "degree", "field_value": "本科", "source": "bert"},
    {"field_key": "skill", "field_value": "Python", "source": "bert"}
  ],
  "quality": {"like_resume": true, "entity_count": 12, "text_chars": 897},
  "created_at": "2026-10-10T15:00:00"
}}
```
> `quality`（T29）：解析质量信号。`done` 但 `like_resume=false` 或 `entity_count=0` 时，前端提示"疑似扫描件/低质量解析"，不阻断流程。

### POST /api/resumes/{id}/reparse ｜无需登录 ｜T29
重新解析（API-14）：用已落盘原件重跑解析流水线，实体与全文索引重建；失败简历或更换模型后可手动触发。
- 响应 `202`：`{"code": 0, "message": "ok", "data": {"resume_id": 1, "parse_status": "pending"}}`
- 404 `E4041`：简历不存在，或原件文件缺失（无法重解析）

### GET /api/resumes/search?q=关键词&limit=20 ｜无需登录 ｜T29
全文搜索（API-15）：FTS5 trigram 中文子串检索（≥3字符）；1-2 字符自动降级 LIKE。命中片段 `snippet` 带「」高亮。
- 响应 `200`：`{"code": 0, "message": "ok", "data": {"total": 1, "items": [{"resume_id": 1, "file_name": "张三.pdf", "parse_status": "done", "created_at": "…", "snippet": "…「搜索词」…"}]}}`
- 400 `E4001`：q 为空白

### GET /api/resumes/{id}/data ｜无需登录 ｜T29
解析数据视图（API-16）：返回这份简历"被读成的数据"——解析全文、实体明细（含来源）、匹配输入 structured_text、向量预览（前8维+维度+模长，实时编码仅供查看，不影响匹配缓存）。
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {
  "resume_id": 1, "file_name": "张三.pdf", "parse_status": "done", "parse_error": null,
  "stats": {"text_chars": 897, "entity_count": 12, "bert_count": 5, "rule_count": 7},
  "entities": [{"field_key": "name", "field_value": "张三", "source": "bert"}],
  "raw_text": "（解析全文）",
  "matching": {"structured_text": "技能：Python 职位：后端开发工程师 …",
               "vector_dim": 768, "vector_norm": 5.1234, "vector_preview": [0.01, -0.02],
               "note": "向量仅展示前8维；匹配实际使用完整向量与缓存"}
}}
```

### DELETE /api/resumes/{id} ｜无需登录 ｜P1
- 响应 `200`：`{"code": 0, "message": "ok", "data": {"resume_id": 1, "deleted": true}}`
- 级联清除：实体、原件文件、全文索引（T29）

> 解析并发（T29）：后台上传解析固定 **2 路并行**（env `PARSE_CONCURRENCY` 可调），其余任务在 pending 排队，防止批量上传挤占 CPU。

### GET /api/resumes/{id}/file ｜无需登录
下载/查看简历原件（API-13）。前端"点击文件名/查看原件"即打开本接口。
- 响应 `200`：文件流，`Content-Disposition` 携带上传时原文件名（PDF 浏览器内预览，DOCX 触发下载）
- 404 `E4041`：resume_id 无效，或原件文件已缺失（早于原件落盘功能的历史数据）

---

## 2. 岗位 JD 模块（M02）

### POST /api/jds ｜无需登录
- 请求体：
```json
{"title": "Python后端工程师", "content": "负责后端服务开发。要求：3年Python经验，熟悉FastAPI，本科及以上。"}
```
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {"jd_id": 1, "title": "Python后端工程师"}}
```
> 说明：`content` 原文入库；结构化要求（学历/年限/技能列表）由规则+NER 离线抽取写入 `req_json`，前端无需提交。

### GET /api/jds ｜无需登录
- 响应 `200`：`{"code": 0, "message": "ok", "data": {"total": 1, "items": [{"jd_id": 1, "title": "Python后端工程师", "created_at": "2026-10-10T15:00:00"}]}}`

### GET /api/jds/{id} ｜无需登录
- 响应 `200`：含 `content` 与 `req_json`（结构化要求对象）

---

## 3. 匹配任务模块（M02 核心）

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
- 响应 `200`（任务 done 后有效；任务未完成时调用返回 `409 E4091`）：
```json
{"code": 0, "message": "ok", "data": {"task_id": 1, "jd_title": "Python后端工程师", "items": [
  {"rank": 1, "resume_id": 1, "candidate_name": "张三", "score": 0.87,
   "evidence": ["技能重叠：Python/FastAPI (2/2)", "学历满足：硕士≥本科", "经验满足：5年≥3年"]}
]}}
```
> score 为语义相似度（0–1，4位小数）；evidence 文案格式定稿见 [算法设计.md](算法设计.md) §4（全角冒号，前端原样展示）。

---

## 4. 报告模块（M05）｜P1

### GET /api/reports/{task_id}/export ｜无需登录
- 响应：`200`，`Content-Type: application/pdf`，文件流（评估报告，含排名、证据链、匹配分布）

---

## 5. 模型信息模块（M01/M03）

### GET /api/model/info ｜无需登录
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {"model_name": "bert-base-chinese-ner", "version": "v0.1", "f1": 0.85, "train_samples": 12000, "updated_at": "..."}}
```

---

## 附：离线评测说明（无 HTTP 接口）

M04 的三组对比实验以 `backend/tools/` 下脚本运行（TF-IDF 基线 / DeepSeek 零样本基线 / 本系统 BERT），产出指标表与图表文件入 `docs/`，不占用任何运行时接口。
