# recruiter-agent — 智能招聘初筛与人才匹配系统

> 人工智能项目工程实践课程项目 ｜ 多Agent协作：解析Agent → 匹配Agent → 报告生成 ｜ 3人团队

HR 上传一批简历并用自然语言描述招聘需求，系统自动解析全部简历、检索并交叉验证，输出**带证据链的候选人排名**，支持一键导出评估报告。

## 架构

```
┌─────────────────┐      /api 代理      ┌──────────────────────────┐
│ frontend (5173) │ ──────────────────> │ backend FastAPI (8000)   │
│ Vite + React    │                     │  api/  接口层（薄）        │
└─────────────────┘                     │  svc/  服务层（Agent/LLM） │
                                        └────┬───────────┬─────────┘
                                             │           │
                                    SQLite(db/)   ChromaDB(db/chroma/)
                                    业务数据          向量检索
                                             │
                                    DeepSeek-V4.1-Flash API
```

## 启动步骤（新成员 10 分钟跑通）

前置：Python 3.11+、Node 18+

### 1. 配置密钥

```bash
cp .env.example backend/.env      # Windows Git Bash；CMD 用 copy
# 编辑 backend/.env，填入你的 DEEPSEEK_API_KEY（sk-开头）
```

### 2. 启动后端（端口 8000）

```bash
cd backend
python -m venv .venv                       # 首次
./.venv/Scripts/python -m pip install -r requirements.txt   # 首次
./.venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload
# 验证：浏览器开 http://127.0.0.1:8000/health → {"status":"ok"}
```

### 3. 启动前端（端口 5173）

```bash
cd frontend
npm install        # 首次
npm run dev
# 浏览器开 http://localhost:5173 → 显示"✅ 后端联通正常"
```

## 常用命令

| 命令 | 说明 |
|---|---|
| `cd backend && .venv/Scripts/python -m pytest -q` | 跑后端单测 |
| `npm run build`（frontend） | 前端构建验证 |
| `sqlite3 ../db/recruiter.db < db/schema.sql`（db 目录下执行） | 重建业务库 |
| `git checkout -b feat/xxx` | 开新功能分支（规范见下） |

## 目录结构

```
├── backend/    FastAPI 后端（app/api 接口层、app/svc 服务层、tests 单测）
├── frontend/   Vite+React 前端
├── docs/       契约与状态表（模块划分/backend-api/technical/test-cases/status四表）
├── db/         schema.sql（唯一数据源）+ 运行期数据（不入库）
├── .env.example  环境变量模板（真实密钥只放 backend/.env，永不提交）
└── README.md
```

## 协作纪律（每轮开发必须遵守）

1. **契约先行**：改接口先改 [docs/backend-api.md](docs/backend-api.md)，再改代码
2. **状态表联动**：实现完成必须同步更新 [docs/status/](docs/status/) 对应表（备注填 commit+日期），无联动不算完成
3. **提交规范**：`类型(范围): 中文描述`，正文列要点；小改动攒着合并提交。类型：feat/fix/docs/refactor/test/chore
4. **分支模型**：`main` 保护，开发走 `feat/模块-功能` 分支 → PR → 另一人 review 后合入
5. **数据库向后兼容**：共享表加列必须带 DEFAULT；破坏性变更全员同拍，改表前备份 `recruiter.db`
6. **密钥纪律**：`.env` 永不进 git；推送前确认历史提交无密钥
7. **验证纪律**：每次改动 = 单测 + 构建 + 冒烟全绿（步骤见 [docs/test-cases.md](docs/test-cases.md)）

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/模块划分文档.md](docs/模块划分文档.md) | 模块编号、接口归属、优先级、认领 |
| [docs/backend-api.md](docs/backend-api.md) | API 契约（唯一准绳） |
| [docs/status/](docs/status/) | api/svc/b-int/modules 四张状态表 |
| [docs/technical.md](docs/technical.md) | 架构决策、数据库设计、外部服务接入 |
| [docs/test-cases.md](docs/test-cases.md) | 测试用例与冒烟步骤 |
