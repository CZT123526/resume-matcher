# backend-api.md — API 契约（唯一准绳）

> **改接口必须先改本文档再改代码**；前后端联调以本文档为准。
> 每个字段的类型/约束/示例见 [api-schemas.md](api-schemas.md)（代码契约：`backend/app/schemas/`）。
> 架构约定：**运行时零外部 API 依赖**，全部推理由本地 BERT 完成；DeepSeek 仅存在于离线评测脚本（不提供 HTTP 接口）。
> 实现进度见 [status/api.md](status/api.md)。

## 通用约定

- Base URL：`http://127.0.0.1:8000`；前端经 Vite 代理以 `/api` 前缀访问
- 认证（T54）：除豁免面（`/health`、`/`、`/docs`、`/openapi.json`、`/redoc`、`/api/auth/login`）外全部接口**需登录**——请求头 `Authorization: Bearer <token>`，token 由 `POST /api/auth/login` 签发；未登录/过期/无效返回 `401 E4011`。豁免面清单以 `backend/app/core/security.py` 为准。测试环境可用 `AUTH_ENABLED=0` 一键关闭（见 test_auth.py 专项覆盖）
- 成功响应统一包裹：`{"code": 0, "message": "ok", "data": {...}}`
- 失败响应：HTTP 状态码 + `{"code": "E####", "message": "错误说明", "data": null}`；参数错误时 message 附带字段明细
- 时间格式：统一 ISO 8601（`T` 分隔），如 `2026-10-10T15:00:00`

### 错误码表

| HTTP | code | 含义 | 触发场景示例 |
|---|---|---|---|
| 400 | E4001 | 参数错误 | 缺少必填字段、top_k 超范围 |
| 400 | E4002 | 文件类型不支持 | 上传 .exe / 空文件 |
| 401 | E4011 | 未登录或凭证失效 | 未携带 token / token 过期或无效（T54） |
| 404 | E4041 | 资源不存在 | resume_id / task_id 无效 |
| 409 | E4091 | 状态冲突 | 任务运行中重复发起 |
| 413 | E4131 | 文件过大 | 简历 > 10MB |
| 500 | E5001 | 服务内部错误 | 未捕获异常 |

---

## 0. 健康检查

### GET /health ｜无需登录（豁免面） ｜✅ 已实现
- 直连探活；`GET /api/health` 为代理路径别名（前端统一走 `/api` 前缀）
- 响应：`{"status": "ok"}`

---

## 1. 简历模块（M01）

### POST /api/resumes/upload ｜需登录
上传简历，后台异步解析（BERT NER 抽取），返回 resume_id 供轮询。
- 请求：`multipart/form-data`，字段 `file`（PDF/DOCX，≤10MB）；批量上传由前端多选后逐份调用本接口
- 原件同步保存至服务端 `db/uploads/{resume_id}.{ext}`（不入 git），供下方 `GET /{id}/file` 查看；删除简历时原件一并清理
- 响应 `202`：
```json
{"code": 0, "message": "ok", "data": {"resume_id": 1, "file_name": "张三.pdf", "parse_status": "pending"}}
```

### GET /api/resumes ｜需登录
- Query：`page=1`、`page_size=20`、`parse_status=pending|processing|done|failed`（可省）、`corpus=all|business|rewrite|semispec|fresh`（可省，语料筛选）
- `corpus` 按批次时间窗区分（app/api/resumes.py `CORPUS_WINDOWS`）：`rewrite` 为 T37 改写简历 160 份、`semispec` 为 T38 半规范简历 100 份、`fresh` 为 T46 外校卷全新岗位简历 50 份，`business` 为窗口外全部（含此后新上传）；响应恒带五类计数 `corpus_counts`，前端下拉直接展示
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {"total": 2, "items": [
  {"resume_id": 1, "file_name": "张三.pdf", "parse_status": "done", "created_at": "2026-10-10T15:00:00"}
], "corpus_counts": {"all": 1372, "business": 1062, "rewrite": 160, "semispec": 100, "fresh": 50}}}
```

### GET /api/resumes/{id} ｜需登录
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {
  "resume_id": 1, "file_name": "张三.pdf", "parse_status": "done", "parse_error": null,
  "raw_text": "（原文全文，T30.1 起不再截 500 字）",
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

### POST /api/resumes/{id}/reparse ｜需登录 ｜T29
重新解析（API-14）：用已落盘原件重跑解析流水线，实体与全文索引重建；失败简历或更换模型后可手动触发。
- 响应 `202`：`{"code": 0, "message": "ok", "data": {"resume_id": 1, "parse_status": "pending"}}`
- 404 `E4041`：简历不存在，或原件文件缺失（无法重解析）

### GET /api/resumes/search?q=关键词&limit=20 ｜需登录 ｜T29
全文搜索（API-15）：FTS5 trigram 中文子串检索（≥3字符）；1-2 字符自动降级 LIKE。命中片段 `snippet` 带「」高亮。
- 响应 `200`：`{"code": 0, "message": "ok", "data": {"total": 1, "items": [{"resume_id": 1, "file_name": "张三.pdf", "parse_status": "done", "created_at": "…", "snippet": "…「搜索词」…"}]}}`
- 400 `E4001`：q 为空白

### GET /api/resumes/{id}/data ｜需登录 ｜T29
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

### GET /api/resumes/{id}/jd_recommendations?top_k=3 ｜需登录 ｜T39
反向推荐（API-17）：给定一份简历，返回它最适合的 Top-K 岗位。评分是**跨 JD 比较**，
用双侧校准（§3.2c）：`score = α·语义百分位 + (1−α)·词面命中率（关键词<3 个向中性收缩）`，
α 取 `MATCH_ALPHA`。**注意 score 为校准融合分，与正向匹配接口（POST /api/match-tasks）
的分数口径不同，不可直接比较**；正向链路不受影响（JD 内部排序对单调变换不敏感）。
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {
  "resume_id": 57,
  "items": [{"jd_id": 16, "title": "Java后端开发工程师", "score": 0.8198,
             "semantic_percentile": 0.9569, "keyword_hit": 0.5, "n_keywords": 8,
             "evidence": ["技能重叠：Spring/MySQL/Redis/Java (4/8)", "缺少技能：Spring Boot、CI/CD"]}]}
}
```
- `score` ∈ [0,1] 降序；`semantic_percentile` = 该简历语义分在本岗位全池分布中的百分位；
  `keyword_hit`/`n_keywords` = 词面命中率/抽取关键词数（原始值，未收缩）；`evidence` 同正向证据链（只解释不打分）
- 400 `E4001`：简历尚未解析完成（top_k 合法域 1~10，越界由统一 400 包裹返回）
- 404 `E4041`：简历不存在，或岗位库为空

### GET /api/resumes/{id}/risk ｜需登录 ｜T55
简历风控体检（API-22）：四类规则检测——时间线矛盾 / 技能脱节 / 疑似克隆 / 联系方式格式异常，
输出结构化 findings 供人工复核。**免责口径：系统只能暴露文本中的矛盾点，技术上无法判定
简历真假，提示不构成造假判定**；证据凑不齐的检查项直接缺席（信息不足不出行），不硬造提示。
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {
  "resume_id": 1,
  "findings": [
    {"level": "risk", "text": "经历时间线存在重叠",
     "evidence": "2023.01-2024.05 与 2023.06-至今"},
    {"level": "warn", "text": "技能 Docker 无经历描述支撑"}
  ],
  "summary": "发现 1 项风险信号、1 项提示，建议人工复核",
  "checked_at": "2026-11-10T15:30:00"
}}
```
- `level`：`ok` 未发现矛盾点（findings 仅一条总述）/ `warn` 提示人工留意 / `risk` 明显矛盾；
  每条 finding 可带 `evidence` 原文引用
- 400 `E4001`：简历尚未解析完成
- 404 `E4041`：简历不存在
- 克隆检测只在**业务投递池**（`source='business'`）内比对：向量近邻余弦 ≥0.98 且姓名实体
  不同；评测语料为模板生成数据、天然近重复，不参与比对。向量缓存不可用（未建库/已失效）
  时该项如实跳过——视图端点不触发重建，重建由匹配/反向推荐链路负责

### DELETE /api/resumes/{id} ｜需登录 ｜P1
- 响应 `200`：`{"code": 0, "message": "ok", "data": {"resume_id": 1, "deleted": true}}`
- 级联清除：实体、原件文件、全文索引（T29）

> 解析并发（T29）：后台上传解析固定 **2 路并行**（env `PARSE_CONCURRENCY` 可调），其余任务在 pending 排队，防止批量上传挤占 CPU。

### GET /api/resumes/{id}/file ｜需登录
下载/查看简历原件（API-13）。前端"点击文件名/查看原件"即打开本接口。
- 响应 `200`：文件流，`Content-Disposition` 携带上传时原文件名（PDF 浏览器内预览，DOCX 触发下载）
- 404 `E4041`：resume_id 无效，或原件文件已缺失（早于原件落盘功能的历史数据）

---

## 2. 岗位 JD 模块（M02）

### POST /api/jds ｜需登录
- 请求体：
```json
{"title": "Python后端工程师", "content": "负责后端服务开发。要求：3年Python经验，熟悉FastAPI，本科及以上。"}
```
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {"jd_id": 1, "title": "Python后端工程师"}}
```
> 说明：`content` 原文入库；结构化要求（学历/年限/技能列表）由规则+NER 离线抽取写入 `req_json`，前端无需提交。

### GET /api/jds ｜需登录
- 响应 `200`：`{"code": 0, "message": "ok", "data": {"total": 1, "items": [{"jd_id": 1, "title": "Python后端工程师", "created_at": "2026-10-10T15:00:00"}]}}`

### GET /api/jds/{id} ｜需登录
- 响应 `200`：含 `content`、`req_json`（结构化要求对象）与 `match_task_count`（名下匹配任务数，T32）

### DELETE /api/jds/{id} ｜需登录 ｜T32
- 响应 `200`：`{"code": 0, "message": "ok", "data": {"jd_id": 1, "deleted": true, "deleted_match_tasks": 2}}`
> 说明：名下匹配任务**连带删除**（任务结果随外键 `ON DELETE CASCADE` 清除），`deleted_match_tasks` 如实报告删除数，不静默丢失；JD 不存在 → 404。

---

## 3. 匹配任务模块（M02 核心）

### POST /api/match-tasks ｜需登录
- 请求体：
```json
{"jd_id": 1, "top_k": 10}
```
- 响应 `202`：
```json
{"code": 0, "message": "ok", "data": {"task_id": 1, "status": "pending"}}
```

### GET /api/match-tasks/{id} ｜需登录
轮询任务状态（前端 2s 间隔）。
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {"task_id": 1, "status": "running", "progress": 60, "error": null}}
```
> status：`pending → running → done | failed`；progress 为 0–100

### GET /api/match-tasks/{id}/results ｜需登录
- 响应 `200`（任务 done 后有效；任务未完成时调用返回 `409 E4091`）：
```json
{"code": 0, "message": "ok", "data": {"task_id": 1, "jd_title": "Python后端工程师", "items": [
  {"rank": 1, "resume_id": 1, "candidate_name": "张三", "score": 0.87,
   "score_detail": {"semantic": 0.9105, "lexical": 0.7667, "alpha": 0.7},
   "evidence": ["符合：Python", "符合：FastAPI", "不符合：Docker", "符合：学历 硕士≥本科", "符合：经验 5年≥3年"]}
]}}
```
> score = α·semantic + (1−α)·lexical（融合回算一致，测试有断言）；score_detail 为 T42 构成明细，历史任务行为 `null`，前端据此隐藏明细行；evidence 文案格式定稿见 [算法设计.md](算法设计.md) §4（全角冒号，前端原样展示）。

### GET /api/match-tasks/{id}/score_distribution ｜需登录 ｜T40
- 全量分数分布：任务完成时流水线把**全部**候选简历的融合分存档 `match_score_dist`（与 Top-K 结果**同一批分数**，`ranking.hybrid_scores` 一次融合两处消费），本接口原样返回供前端画分布图。
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {"task_id": 1, "jd_title": "Python后端工程师",
  "n_candidates": 1322, "scores": [0.9214, 0.8857, "…（降序，4位小数）"],
  "items": [{"resume_id": 1, "score": 0.9214, "name": "张三"}, "…与 scores 严格同序"]}}
```
> `items` 为 T43 候选人明细（点分布图柱子反查分数段简历用）；历史任务（存档表无 ids_json）返回空数组，前端点击自动忽略。历史任务（存档表无行）返回 `n_candidates: 0, scores: [], items: []`，前端据此隐藏分布图，不算错误。
- 错误：`404 E4041` 任务不存在；`409 E4091` 任务未完成（同 results 口径）。

---

## 4. 报告模块（M05）｜P1

### GET /api/reports/{task_id}/export ｜需登录
- 响应：`200`，`Content-Type: application/pdf`，文件流（评估报告，含排名、证据链、匹配分布）

---

## 5. 模型信息模块（M01/M03）

### GET /api/model/info ｜需登录
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {"model_name": "bert-base-chinese-ner", "version": "v0.1", "f1": 0.85, "train_samples": 12000, "updated_at": "..."}}
```

---

## 6. 主页统计模块（T48，API-19）

### GET /api/stats/home ｜需登录
主页总览：库规模计数 + 两类排名，全部实时聚合、只读无写入。
- 响应 `200`：
```json
{"code": 0, "message": "ok", "data": {
  "resumes": {"all": 1372, "business": 1062, "rewrite": 160, "semispec": 100, "fresh": 50, "parsed_done": 1372},
  "jd_count": 65, "jd_covered": 12, "match_done": 35,
  "title_kinds": 165, "title_resumes": 1186,
  "title_rank": [{"title": "后端开发工程师", "n": 42}, "…降序，最多 10 条"],
  "jd_rank": [{"jd_id": 20, "title": "商业数据分析师", "recalled": 50, "task_count": 3, "last_run_at": "2026-10-20T13:41:21"}, "…按 recalled 降序，最多 10 条"]
}}
```
> 口径说明：`resumes` 五类计数与简历列表页 `corpus_counts` 同一算法（按 `resumes.source` 显式列，T53 起上传即标记），`all` 恒等于四类之和；
> `title_rank` 为简历应聘岗位排名，按解析出的任职/应聘岗位名称统计简历数，一份简历可命中多个岗位名、均计入，未抽到岗位字段的简历不计入；
> `jd_rank` 为岗位人才储备排名，每个岗位取**最近一次完成的**匹配任务，`recalled` 为该次任务召回的简历份数（受当次 `top_k` 设置影响，历史数据如实展示不补算），`task_count` 为该岗位累计完成的匹配任务数；
> 从未跑过匹配的岗位不进榜，覆盖面用 `jd_covered` / `jd_count` 如实披露。

---

## 7. 认证模块（T54 安全加固）

HR 账号体系：密码 pbkdf2-hmac-sha256 哈希存储（零第三方依赖）；会话 token 服务端随机生成、库中只存其 SHA-256 哈希（库文件泄露不可复用）；首次启动 users 表为空时按 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 环境变量创建管理员（未设置则默认 `admin`/`admin123` 并在日志 ⚠ 提示立即改密）。

### POST /api/auth/login ｜无需登录（豁免面）
- 请求 `{"username": "admin", "password": "…"}`
- 响应 `200`：`{"code":0, "data": {"username": "admin", "role": "admin", "token": "<urlsafe随机串>", "expires_at": "2026-11-11T00:00:00"}}`
- 失败：`401 E4011` 用户名或密码错误（文案不区分两者，防枚举）；审计记录 login 成败（含 ip）

### POST /api/auth/logout ｜需登录
- 响应 `200`：`{"code":0, "data": {"logged_out": true}}`——删除当前 token 的服务端会话行

### GET /api/auth/me ｜需登录
- 响应 `200`：`{"code":0, "data": {"username": "admin", "role": "admin"}}`

### 隐私保护口径（T54 同批）
- PII 打码：手机号（`1[3-9]` 开头 11 位）、邮箱、身份证在**详情 `raw_text`、`/data` 视图、搜索 snippet**默认打码；详情/数据视图支持 `?reveal=1` 显示原文（记审计 `reveal_pii`）；搜索 snippet 强制打码不可 reveal
- 导出 PDF 中候选人姓名默认打码（如 `张*`），`?reveal=1` 显示全名（记审计）
- 访问审计：`audit_log` 表记录 谁/何时/做了什么（登录成败、注销、查看简历、下载原件、导出报告、删除、上传、发起匹配、查看风控、显示 PII），写入失败不影响业务

---

## 附：离线评测说明（无 HTTP 接口）

M04 的三组对比实验以 `backend/tools/` 下脚本运行（TF-IDF 基线 / DeepSeek 零样本基线 / 本系统 BERT），产出指标表与图表文件入 `docs/`，不占用任何运行时接口。
