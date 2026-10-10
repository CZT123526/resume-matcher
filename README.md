# resume-matcher — 简历智能解析与人才推荐系统

> 人工智能项目工程实践课程项目 ｜ 《基于BERT与多模型对比的简历智能解析与人才推荐系统》｜ 3人团队
> 技术路线：**BERT NER 抽取 + BERT 语义匹配 + 多模型对比评测；运行时全本地，零外部 API 依赖**

HR 上传一批简历并输入岗位 JD，系统用本地 BERT 模型完成实体抽取与语义匹配，输出**带证据链的候选人排名**。TF-IDF 与 DeepSeek 零样本作为离线对照组，量化证明本地方案在精度/延迟/成本/可离线部署上的工程价值。

## 架构

```
┌─────────────────┐      /api 代理      ┌────────────────────────────┐
│ frontend (5173) │ ──────────────────> │ backend FastAPI (8000)     │
│ Vite + React    │                     │  api/  接口层（薄）          │
└─────────────────┘                     │  svc/  服务层（BERT推理）    │
                                        │  tools/ 离线评测脚本         │
                                        └────┬───────────────────────┘
                                             │
                                   SQLite(db/) + vectors.npy
                                   业务数据       语义向量缓存
                                             │
                              bert-base-chinese（本地推理，CPU可跑）
                              训练：Google Colab T4
                              离线对照：TF-IDF ｜ DeepSeek 零样本（不进运行时）
```

## 启动步骤（新成员 10 分钟跑通）

前置：Python 3.11+、Node 18+

### 1. 配置密钥（仅离线评测需要；先跑通骨架可跳过）

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
# 验证：浏览器开 http://127.0.0.1:8000/api/health → {"status":"ok"}
```

### 3.（可选）装 BERT 运行时——不装则自动降级 TF-IDF，系统照样可用

```bash
./.venv/Scripts/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
./.venv/Scripts/python -m pip install "transformers>=4.41"
# 首次跑匹配任务时会经 hf-mirror 自动下载 bert-base-chinese（约 400MB，进本地缓存不进 git）
```

NER 微调模型训练好放到 `backend/models/ner/` 即自动启用（实体抽取 source 变 bert，
skill/years/school 等模型无标签字段仍由规则兜底，见 `app/svc/ner.py` 字段级合并）。

### 4. 启动前端（端口 5173）

```bash
cd frontend
npm install        # 首次
npm run dev
# 浏览器开 http://localhost:5173 → 显示"✅ 后端联通正常"
```

## 常用命令

| 命令 | 说明 |
|---|---|
| `cd backend && .venv/Scripts/python -m pytest -q` | 跑后端单测（62 个） |
| `npm run build`（frontend） | 前端构建验证 |
| `cd backend && .venv/Scripts/python scripts/smoke_e2e.py` | 起服后跑端到端冒烟（另开终端） |
| `cd backend && .venv/Scripts/python tools/run_experiments.py` | 三组对比实验 → docs/eval/ |
| `cd backend && .venv/Scripts/python tools/data/download_dataset.py` | 下载简历NER数据集并转语料 |
| `cd backend && NER_DATA_DIR=... python tools/train_ner.py` | NER 微调（建议 Colab T4，见脚本头部） |
| `docker compose up --build` | 一键全栈（需 Docker） |
| `git checkout -b feat/xxx` | 开新功能分支（规范见下） |

## 目录结构

```
├── backend/    FastAPI 后端（app/api 接口层、app/schemas 数据契约、app/svc 服务层、
│               app/core 异常体系、tools 离线评测与训练、tests 单测）
│               models/ner/ —— NER 微调产物放这里即自动启用（不入库）
├── frontend/   Vite+React 前端
├── docs/       图纸（算法设计/api-schemas/开发规范/backend-api/technical）+ status 四表
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
8. **架构红线**：`backend/app/` 内禁止出现任何外部 API 调用；DeepSeek 只允许存在于 `backend/tools/` 离线评测脚本

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/模块划分文档.md](docs/模块划分文档.md) | 模块编号、接口归属、优先级、认领 |
| [docs/backend-api.md](docs/backend-api.md) | API 契约（唯一准绳） |
| [docs/api-schemas.md](docs/api-schemas.md) | 接口字段级规格（联调细节以它为准） |
| [docs/算法设计.md](docs/算法设计.md) | 抽取Schema/NER/匹配/证据链/评测协议 |
| [docs/开发规范.md](docs/开发规范.md) | 分层规则、PR模板、mock方案、DoD、性能预期 |
| [docs/status/](docs/status/) | api/svc/b-int/modules 四张状态表 |
| [docs/technical.md](docs/technical.md) | 架构决策、数据库设计、模型接入要点 |
| [docs/test-cases.md](docs/test-cases.md) | 测试用例、冒烟步骤、零API专项检查 |
