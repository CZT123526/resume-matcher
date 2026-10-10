# status/api.md — 接口实现状态表

> 纪律：**代码实现完必须同步更新本表**（备注列填 commit 短哈希 + 日期）。
> 状态取值：未开始 ｜ 进行中 ｜ 已完成 ｜ 已验收（对方成员联调通过）

| 编号 | 名称 | 说明 | 负责人 | 状态 | 备注 |
|---|---|---|---|---|---|
| API-00 | GET /health | 探活 | 成员B | 已完成 | `a1b2c3d` 2026-10-10 |
| API-01 | POST /api/resumes/upload | 上传简历并异步解析 | 成员B | 未开始 | M01 |
| API-02 | GET /api/resumes | 简历分页列表 | 成员B | 未开始 | M01 |
| API-03 | GET /api/resumes/{id} | 简历详情+实体 | 成员B | 未开始 | M01 |
| API-04 | DELETE /api/resumes/{id} | 删除简历 | 成员B | 未开始 | M01/P1 |
| API-05 | POST /api/jds | 创建岗位JD | 成员B | 未开始 | M03 |
| API-06 | GET /api/jds | JD列表 | 成员B | 未开始 | M03 |
| API-07 | GET /api/jds/{id} | JD详情(含req_json) | 成员B | 未开始 | M03 |
| API-08 | POST /api/match-tasks | 发起匹配任务 | 成员B | 未开始 | M03 |
| API-09 | GET /api/match-tasks/{id} | 任务状态轮询 | 成员B | 未开始 | M03 |
| API-10 | GET /api/match-tasks/{id}/results | 匹配结果(排名+证据) | 成员B | 未开始 | M03 |
| API-11 | POST /api/chat | HR对话入口(调度Agent) | 成员B | 未开始 | M03/M04 |
| API-12 | GET /api/reports/{task_id}/export | PDF报告导出 | 成员A | 未开始 | M05/P1 |
| API-13 | GET /api/model/info | 模型版本与指标 | 成员A | 未开始 | M02/P1 |
| API-14 | POST /api/admin/distill | 触发标注+训练流水线 | 成员A | 未开始 | M02/P1 |
