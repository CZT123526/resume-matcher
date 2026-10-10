# technical.md — 技术文档

> 记录架构决策与关键设计。新人入职先读本文档 + README。
> 技术路线以《开题报告人工智能创新实践项目(2)》为准：**去Agent化、运行时全本地、DeepSeek 仅作离线对照**。

## 1. 架构分层与理由

```
frontend/ (Vite+React, 5173)         纯展示与交互，业务逻辑不下前端
    │  fetch /api/*（Vite 代理）
backend/app/
    ├── main.py        应用装配（FastAPI 实例、CORS、全局异常处理、路由挂载）
    ├── config.py      配置中心（.env 注入，密钥不落代码）
    ├── api/           接口层：参数校验 + 调服务层 + 统一响应包裹；禁止写业务逻辑
    ├── schemas/       数据契约：全部请求/响应的 Pydantic 模型（对应 docs/api-schemas.md）
    ├── core/          横切组件：统一错误码与 AppError 异常体系
    ├── common/        通用工具：统一响应包裹 ok()/fail()
    ├── svc/           服务层：业务逻辑 + 模型推理封装；签名契约见 svc/contracts.py（S01–S11）；
    │                  数据访问(SQLite)也在此层，3人项目不单拆 dao 层，避免过度设计
    ├── tools/         离线脚本：训练、评测基线、DeepSeek 对照（不进请求链路，禁止被 app/ import）
    └── tests/         pytest 单测；每次改动必须全绿
db/  schema.sql（唯一数据源）+ 运行期 recruiter.db + vectors.npy 语义向量缓存（均不入库）
docs/ 契约与状态表（契约先行）：算法设计.md / api-schemas.md / 开发规范.md 为三大图纸
```

**分层理由**：接口契约稳定（前端依赖它），模型实现可替换（NER 模型升级版本、换底座，Schema 不变即插即用）。
**面向接口编程的落地**：三层契约——HTTP 契约（backend-api.md + api-schemas.md）、数据契约（schemas/ 代码）、服务契约（svc/contracts.py 签名即契约）；变更流程见 docs/开发规范.md §1。

## 2. 关键设计决策

| # | 决策 | 备选项 | 选择理由 |
|---|---|---|---|
| D1 | **Monorepo 单仓双目录** | 前后端两仓 | 3人课程项目，API契约/状态表强耦合；单仓一次PR可同时改两端与文档 |
| D2 | **SQLite 单库**（无独立向量库） | MySQL、ChromaDB | 万级简历的语义向量用 numpy 矩阵余弦直算即可（毫秒级），独立向量库是过度设计；少一个组件，Docker 部署与演示少一分风险。向量缓存为 `db/vectors.npy` + id 映射表 |
| D3 | **运行时零 API 依赖** | LLM 在线调用 | 答辩断网可演示；DeepSeek 仅作对照组二离线跑分（见 D6） |
| D4 | **异步任务 + 轮询**（解析/匹配） | WebSocket/SSE | 轮询实现最简单且足够；先跑通，中期有余力再升级 |
| D5 | **同一 BERT 底座双任务复用** | 两套模型 | bert-base-chinese 一个底座：NER 微调头（实体抽取）+ 原生语义编码（JD/简历向量化），省显存省工作量，且"多模型对比"故事集中 |
| D6 | **评测金标准自动构造** | 人工标注 | 利用公开简历数据集自带的"期望岗位/工作经历"字段自动构造 JD-简历正样本对，负样本随机采样；另人工抽检 50~100 对校验噪声率——解决 NDCG@K/F1 的 ground truth 来源问题 |
| D7 | **数据域以内业简历集为主** | 直接用 CLUENER | CLUENER2020 是通用领域 NER，只作 NER 训练的辅助/预训练语料；简历领域数据为主，规避域偏移质疑 |

## 3. 数据库设计

完整建表 SQL 见 [db/schema.sql](../db/schema.sql)（**唯一数据源**，改表先改它）。表关系：

```
jds 1──∞ match_tasks 1──∞ match_results ∞──1 resumes 1──∞ entities
users（权限预留，未启用）
```

要点：
- 5 张业务表 + 1 张预留表；外键 `ON DELETE CASCADE` 按需标注
- `parse_status`/`status` 用 TEXT 存状态机值（pending/processing/done/failed），可读性优先
- `entities.source` 当前恒为 `bert`；大字段 `raw_text` 只在详情接口返回
- 语义向量不入库：`db/vectors.npy`（矩阵）+ `resume_ids.json`（行→resume_id 映射），由 M02 重建与缓存

## 4. 模型与外部服务接入要点

### BERT（本地核心）
- 底座 `bert-base-chinese`；NER 微调数据 = 简历领域标注集（主）+ CLUENER2020（辅，约1.2万条）
- 推理：CPU 可跑（简历解析单份秒级）；训练上 Google Colab T4
- 模型产物放 `backend/models/`（.gitignore 排除，README 提供下载/训练说明）；`GET /api/model/info` 汇报版本与 F1

### DeepSeek（仅离线评测，对照组二）
- 接入仅通过 `tools/baseline_deepseek.py`，走 OpenAI 兼容接口；密钥从 .env 读
- 与运行时代码物理隔离：`backend/app/` 内不得出现任何 DeepSeek 调用——这是"零 API 依赖"承诺的执行边界，code review 检查项

### Google Colab（训练）
- 训练脚本放 `backend/tools/`，数据集挂 Google Drive；产出 model + metrics.json 回传

## 5. 前端要点

- 开发期所有请求走 `/api` 前缀（Vite 代理到 8000），生产由 Nginx 做同样代理——前端代码零改动
- 统一 `request.js` 封装：解 `{code, message, data}` 包裹、统一错误弹窗
- 页面清单：简历上传管理页 / JD输入与匹配页（排名卡片+证据链）/ 任务历史页 / 模型与实验指标展示页（读 metrics.json 静态图表）
