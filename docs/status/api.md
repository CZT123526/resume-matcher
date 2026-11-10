# status/api.md — 接口实现状态表

> 纪律：**代码实现完必须同步更新本表**（备注列填 commit 短哈希 + 日期）。
> 状态取值：未开始 ｜ 进行中 ｜ 已完成 ｜ 已验收（对方成员联调通过）

| 编号 | 名称 | 说明 | 负责人 | 状态 | 备注 |
|---|---|---|---|---|---|
| API-00 | GET /health、/api/health | 探活 | 成员B | 已完成 | `9fdb168` 2026-10-10 |
| API-01 | POST /api/resumes/upload | 上传简历并异步解析(BERT NER) | 成员A | 已完成 | `744d0dd` 2026-10-10；类型/大小/空文件校验，E2E冒烟通过 |
| API-02 | GET /api/resumes | 简历分页列表 | 成员A | 已完成 | `744d0dd` 2026-10-10 |
| API-03 | GET /api/resumes/{id} | 简历详情+实体 | 成员A | 已完成 | `744d0dd` 2026-10-10 |
| API-04 | DELETE /api/resumes/{id} | 删除简历 | 成员A | 已完成 | `744d0dd` 2026-10-10；级联删实体 |
| API-05 | POST /api/jds | 创建岗位JD | 成员B | 已完成 | `2698613` 2026-10-10；创建时同步抽取req_json |
| API-06 | GET /api/jds | JD列表 | 成员B | 已完成 | `2698613` 2026-10-10；含total |
| API-07 | GET /api/jds/{id} | JD详情(含req_json) | 成员B | 已完成 | `2698613` 2026-10-10 |
| API-08 | POST /api/match-tasks | 发起匹配任务 | 成员B | 已完成 | `2698613` 2026-10-10；202+后台任务 |
| API-09 | GET /api/match-tasks/{id} | 任务状态轮询 | 成员B | 已完成 | `2698613` 2026-10-10；进度5→100 |
| API-10 | GET /api/match-tasks/{id}/results | 匹配结果(排名+证据) | 成员B | 已完成 | `2698613` 2026-10-10；未完成409 E4091 |
| API-11 | GET /api/reports/{task_id}/export | PDF报告导出 | 成员A | 已完成 | `1e3f055` 2026-10-10；内嵌中文字体，演示样张 docs/eval/report_demo_task1.pdf |
| API-12 | GET /api/model/info | 模型版本与F1指标 | 成员A | 已完成 | `2698613` 2026-10-10；无训练产物时如实返回v0-rules |
| API-13 | GET /api/resumes/{id}/file | 简历原件下载（上传落盘） | 成员A | 已完成 | `f8ae9c6` 2026-10-11；原件存 db/uploads/{id}.{ext} 不入 git，删除简历级联清理，缺失历史数据 404 兜底 |
| API-14 | POST /api/resumes/{id}/reparse | 重新解析（用落盘原件重跑流水线） | 成员A | 已完成 | `a571298` 2026-10-11；失败简历/换模型后手动触发，202+后台任务，无原件 404 |
| API-15 | GET /api/resumes/search | 简历全文搜索（FTS5 trigram 中文子串） | 成员A | 已完成 | `a571298` 2026-10-11；≥3字 FTS MATCH，1-2字 LIKE 降级，snippet「」高亮 |
| API-16 | GET /api/resumes/{id}/data | 解析数据视图（全文/实体/匹配输入/向量预览） | 成员A | 已完成 | `a571298` 2026-10-11；向量实时编码仅供查看不动缓存 |
| API-17 | DELETE /api/jds/{id} | 删除JD（名下匹配任务连带删除，结果随FK级联） | 成员B | 已完成 | T32 2026-10-12；响应报 deleted_match_tasks；API-07 同步增 match_task_count 字段 |
| API-18 | GET /api/match-tasks/{id}/score_distribution | 全量融合分分布（分布图数据源，T43 候选人明细点柱反查） | 成员B | 已完成 | 补录 T40（PR #29 `66da8ff`，历史任务返回空列表前端隐藏分布图）；T40~T48 批次未同步本表，一并补齐 |
| API-19 | GET /api/stats/home | 主页总览（API-19，T48）：库规模计数+应聘岗位排名+岗位储备排名+覆盖面披露 | 成员B | 已完成 | 补录 T48（PR #30 `643dc90`）；含匹配卡定宽对齐+轮询提速 `33dfa1b` |
| API-20 | POST /api/auth/login、POST /api/auth/logout、GET /api/auth/me | 认证模块（T54）：pbkdf2 哈希、token 只存 SHA-256、首启引导管理员、防枚举同文案 | 成员A | 已完成 | `b18a38d` 2026-11-10；app 级 auth_guard 统一鉴权（豁免面见 core/security.py），401 E4011 |
| API-21 | （横切口）PII 打码 + 访问审计（T54） | 详情//data/snippet/PDF 姓名 默认打码，?reveal=1 显示原文并记审计；audit_log 十类动作写失败不阻塞业务 | 成员A | 已完成 | `b18a38d` 2026-11-10；真库冒烟 17/17（无token 401/打码/reveal/审计落表/注销失效全过） |
