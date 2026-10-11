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
