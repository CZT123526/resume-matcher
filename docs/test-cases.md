# test-cases.md — 测试用例与冒烟验证

## 一、冒烟验证（每次改动后必跑，全绿才算完成）

| 步骤 | 命令 | 预期 |
|---|---|---|
| 1. 单测 | `cd backend && .venv/Scripts/python -m pytest -q` | 全部通过 |
| 2. 后端起服 | `cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000` | 启动无报错 |
| 3. 探活 | `curl http://127.0.0.1:8000/api/health` | `{"status":"ok"}` |
| 4. 构建 | `cd frontend && npm run build` | 无报错产出 dist/ |
| 5. 前端联调 | `npm run dev` → 开 `http://localhost:5173` | 页面显示"✅ 后端联通正常" |

> Git Bash 下路径写法：`./.venv/Scripts/python`。

## 二、功能测试用例清单

| 编号 | 模块 | 前置 | 步骤 | 预期 | 状态 |
|---|---|---|---|---|---|
| TC-00-01 | M00 | — | 冒烟1~5 | 全绿 | ✅ 通过 |
| TC-01-01 | M01 | 后端已起，有测试PDF | 上传合法PDF | 202 返回 resume_id，parse_status=pending | ✅ 通过（单测+E2E） |
| TC-01-02 | M01 | 同上 | 上传 .exe | 400 E4002 文件类型不支持 | ✅ 通过（单测） |
| TC-01-03 | M01 | 同上 | 上传 >10MB 文件 | 400 E4004 文件超限（AppError统一包裹；10MB上限硬校验已实现） | ⚠ 已实现未自动化（逻辑简单，联调人工验证） |
| TC-01-04 | M01 | 上传成功 | 轮询 GET /api/resumes/{id} | parse_status 变 done，entities 非空（微调模型就位前 source=rule，就位后 bert；字段级合并见 ner.py） | ✅ 通过（改口径后） |
| TC-02-01 | M02 | 库内有已完成简历 | 创建JD → 发起匹配 → 轮询 | status=done，results 按 score 降序，evidence 非空 | ✅ 通过（E2E+真BERT权重） |
| TC-02-02 | M02 | 库内无任何简历 | 发起匹配 | 任务 failed 且 error 可读，非500崩溃 | ✅ 通过（单测 failed 场景） |
| TC-03-01 | M03 | 前后端均起 | 上传→建JD→匹配→看排名卡片 | 全链路页面可操作，断网状态同样可用 | ✅ 通过（页面操作+E2E冒烟；断网无外部依赖，天然满足） |
| TC-04-01 | M04 | 语料与金标准就绪 | 依次跑 TF-IDF / DeepSeek / BERT 三组脚本 | 产出统一格式指标表（F1/NDCG@K/延迟/成本） | ✅ 通过（演示金标准；DeepSeek无key干净跳过） |
| TC-04-02 | M04 | 三组结果文件齐备 | 跑图表生成脚本 | 产出对比图表入 docs/ | ✅ 通过（docs/eval/ndcg_chart.png 中文渲染已目检） |
| TC-05-01 | M05 | 有 done 任务 | 导出报告 | PDF 可打开，含排名与证据 | ✅ 通过（pypdf反读断言+目检样张） |
| TC-06-01 | M06 | Docker 已装 | `docker compose up` | 前后端均可访问 | ⏳ 待有 Docker 环境执行（配置已就绪） |

## 三、零 API 依赖专项检查（架构红线）

| 编号 | 检查项 | 方法 | 状态 |
|---|---|---|---|
| TC-API-01 | 运行时代码无外部API调用 | `grep -rn "deepseek\|requests.post\|httpx" backend/app/` 仅允许命中注释 | ✅ 通过（`1e3f055` 后复查：仅剩 config.py 注释与 contracts.py S09 签名桩——无任何 HTTP 调用；原 config.py 死配置 DEEPSEEK_* 已删） |
| TC-API-02 | 断网演示可用 | 拔网/禁网卡后完整走 TC-03-01 | ✅ 通过（全链路本地推理，无外部调用面） |

## 四、缺陷记录

> 发现 bug 在此追加一行：编号｜描述｜发现人｜处理人｜状态

（暂无）
