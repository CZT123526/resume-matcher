# 接口字段级规格（api-schemas）

> `backend-api.md` 定义"有哪些接口"，本文档定义"每个字段长什么样"——前后端联调以这两份为准。
> 代码契约：`backend/app/schemas/`（Pydantic 模型，与本文档同步维护）。
> 变更流程：改本文档 → 改 schemas 代码 → 通知前端（PR 里 @成员C）。

## 0. 通用约定

### 0.1 响应包裹

所有 `/api/*` 接口（除 `/health`）返回：

```json
{"code": 0, "message": "ok", "data": { }}
```

- 成功：`code=0`，`data` 为下表对应结构；
- 失败：`code="E####"`（字符串），`message` 中文可读，`data=null`；
- HTTP 状态码与 code 对应（400/404/409/413/500）。

### 0.2 错误码

| code | HTTP | 含义 | 典型场景 |
|---|---|---|---|
| E4001 | 400 | 参数错误 | 校验失败、JSON 解析失败 |
| E4002 | 400 | 文件类型不支持 | 上传 .exe/.zip |
| E4041 | 404 | 资源不存在 | resume_id/jd_id/task_id 无效 |
| E4091 | 409 | 状态冲突 | 重复提交解析中的简历 |
| E4131 | 413 | 文件过大 | > 10MB |
| E5001 | 500 | 服务内部错误 | 兜底，不含堆栈细节 |

### 0.3 枚举汇总

| 枚举 | 取值 |
|---|---|
| parse_status | `pending → processing → done \| failed` |
| task status | `pending → running → done \| failed` |
| 实体 field_key | `name / degree / school / skill / years / company / title` |

### 0.4 通用格式

- 时间：ISO 8601 字符串 `2026-10-10T12:00:00`
- id：正整数
- 分页：`page` 从 1 起，`page_size` 默认 20、上限 100

---

## 1. 简历模块（M01）

### POST /api/resumes/upload `202`

multipart/form-data：`file`（pdf/doc/docx，≤10MB）。

`data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| resume_id | int | 入库 id |
| file_name | string | 原始文件名 |
| parse_status | enum | 恒为 `pending`（异步解析） |

### GET /api/resumes `200`

Query：`page=1`、`page_size=20`、`parse_status`（可选过滤）。

`data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| total | int | 过滤后的总数 |
| items | array | ResumeListItem[] |
| items[].resume_id | int | |
| items[].file_name | string | |
| items[].parse_status | enum | |
| items[].created_at | string | ISO 8601 |

### GET /api/resumes/{id} `200`

`data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| resume_id | int | |
| file_name | string | |
| parse_status | enum | |
| raw_text | string\|null | 原文全文（T30.1 起不再截断；done 才有） |
| entities | array | EntityItem[] |
| entities[].field_key | enum | 7 类实体 |
| entities[].field_value | string\|null | 规范化值（years 为数字字符串） |
| entities[].source | string | 运行时恒为 `bert` |
| created_at | string | |

失败：E4041（id 不存在）。

### GET /api/resumes/{id}/jd_recommendations?top_k=3 `200` ｜T39

反向推荐（API-17）：这份简历最适合的 Top-K 岗位。`score` 为**校准融合分**
（= α·语义百分位 + (1−α)·词面命中率，关键词<3 个向中性 0.5 收缩；α 取 MATCH_ALPHA），
与正向匹配接口分数口径不同，不可直接比较。

`data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| resume_id | int | |
| items[].jd_id | int | |
| items[].title | string | 岗位名 |
| items[].score | float | 校准融合分 ∈ [0,1]，降序 |
| items[].semantic_percentile | float | 语义分在本岗位全池分布中的百分位 |
| items[].keyword_hit | float | 词面命中率（原始值，未收缩） |
| items[].n_keywords | int | 该 JD 抽取的关键词数 |
| items[].evidence | array | string[]，同正向证据链（只解释不打分） |

失败：E4041（id 不存在 / 岗位库为空）；E4001（简历尚未解析完成；top_k 越界由统一 400 包裹）。

### DELETE /api/resumes/{id} `200`（P1）

删除简历及其关联实体；若已生成向量缓存，标记缓存失效（下次任务前重建）。

`data`：`{"resume_id": int, "deleted": true}`

失败：E4041（id 不存在）。

---

## 2. JD 模块（M02）

### POST /api/jds `200`

Body：`{"title": string(1..100), "content": string(1..5000)}`

`data`：`{"jd_id": int, "title": string}`

> req_json 由后端离线抽取（规则+NER），创建时不接收。

### GET /api/jds `200`

`data.items[]`：`{jd_id, title, created_at}`（外层含 total）。

### GET /api/jds/{id} `200`

`data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| jd_id | int | |
| title | string | |
| content | string | 原文 |
| req_json | object\|null | `{"degree": "本科"\|null, "min_years": 3\|null, "skills": ["Python"]}` |
| match_task_count | int | 名下匹配任务数（T32） |
| created_at | string | |

### DELETE /api/jds/{id} `200` ｜T32

`data`：`{"jd_id": int, "deleted": true, "deleted_match_tasks": int}`

> 名下匹配任务连带删除（match_results 随外键级联清除）。

---

## 3. 匹配任务模块（M02）

### POST /api/match-tasks `202`

Body：`{"jd_id": int, "top_k": int=10, 1..50}`

`data`：`{"task_id": int, "status": "pending"}`

### GET /api/match-tasks/{id} `200`（轮询，2s 间隔）

`data`：`{task_id, status, progress(0..100), error: string|null}`

### GET /api/match-tasks/{id}/results `200`

`data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| task_id | int | |
| jd_title | string | |
| items | array | 按 rank 升序 |
| items[].rank | int | 从 1 起 |
| items[].resume_id | int | 前端拿它跳详情页 |
| items[].candidate_name | string | 来自实体 name，未知显示"候选人{id}" |
| items[].score | float | 0~1，4 位小数；前端展示建议 ×100 取整 |
| items[].evidence | string[] | 证据链文本，见算法设计 §4 |

失败：E4041；任务未完成时调用返回 E4091。

---

## 4. 其他

### GET /api/model/info `200`

`data`：`{model_name, version, f1(0~1), train_samples(int), updated_at}`

### GET /api/reports/{task_id}/export `200`（P1）

返回 `application/pdf` 文件流（不走统一包裹）。

---

## 附：契约代码位置

| 契约 | 代码 |
|---|---|
| 本文档全部字段 | `backend/app/schemas/*.py` |
| 错误码/异常 | `backend/app/core/errors.py`（AppError） |
| 响应包裹 | `backend/app/common/response.py`（ok/fail） |
| svc 层签名 | `backend/app/svc/contracts.py`（S01–S11） |
