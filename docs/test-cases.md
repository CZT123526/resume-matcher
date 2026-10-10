# test-cases.md — 测试用例与冒烟验证

## 一、冒烟验证（每次改动后必跑，全绿才算完成）

| 步骤 | 命令 | 预期 |
|---|---|---|
| 1. 单测 | `cd backend && .venv/Scripts/python -m pytest -q` | 全部通过 |
| 2. 后端起服 | `cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000` | 启动无报错 |
| 3. 探活 | 浏览器/`curl http://127.0.0.1:8000/health` | `{"status":"ok"}` |
| 4. 构建 | `cd frontend && npm run build` | 无报错产出 dist/ |
| 5. 前端联调 | `npm run dev` → 开 `http://localhost:5173` | 页面显示"✅ 后端联通正常" |

> Git Bash 下路径写法：`./.venv/Scripts/python`。

## 二、功能测试用例清单

| 编号 | 模块 | 前置 | 步骤 | 预期 | 状态 |
|---|---|---|---|---|---|
| TC-00-01 | M00 | — | 冒烟1~5 | 全绿 | ✅ 通过 |
| TC-01-01 | M01 | 后端已起，有测试PDF | 上传合法PDF | 202 返回 resume_id，parse_status=pending | 未开始 |
| TC-01-02 | M01 | 同上 | 上传 .exe | 400 E4002 文件类型不支持 | 未开始 |
| TC-01-03 | M01 | 同上 | 上传 >10MB 文件 | 413 E4131 | 未开始 |
| TC-01-04 | M01 | 上传成功 | 轮询 GET /api/resumes/{id} | parse_status 变 done，entities 非空 | 未开始 |
| TC-02-01 | M02 | ≥1万标注语料就绪 | 触发 distill 并等待 | 任务完成，model/info 返回新 F1 | 未开始 |
| TC-03-01 | M03 | 库内有已完成简历 | 创建JD → 发起匹配 → 轮询 | status=done，results 按 score 降序 | 未开始 |
| TC-03-02 | M03 | 库内无任何简历 | 发起匹配 | 任务 failed 且 error 可读，非500崩溃 | 未开始 |
| TC-03-03 | M03 | — | chat 发"找会Python的人" | 返回 intent 与 reply，agent_trace 非空 | 未开始 |
| TC-04-01 | M04 | 前后端均起 | 上传→建JD→匹配→看排名卡片 | 全链路页面可操作 | 未开始 |
| TC-05-01 | M05 | 有 done 任务 | 导出报告 | PDF 可打开，含排名与证据 | 未开始 |
| TC-06-01 | M06 | Docker 已装 | `docker compose up` | 前后端均可访问 | 未开始 |

## 三、缺陷记录

> 发现 bug 在此追加一行：编号｜描述｜发现人｜处理人｜状态

（暂无）
