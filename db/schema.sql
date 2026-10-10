-- ============================================================
-- recruiter-agent 业务库建表脚本（SQLite）
-- 唯一数据源：本文件。改表 = 先改这里并提交，再动代码。
-- 纪律：SQLite 无 COMMENT ON 语法，每个字段用行内 -- 注释说明；
--       共享表加列必须带 DEFAULT（向后兼容，防止他人旧代码插入报错）。
-- 重建命令：sqlite3 ../db/recruiter.db < schema.sql
-- ============================================================

-- 简历原始记录表：一份上传文件一行
CREATE TABLE IF NOT EXISTS resumes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- 简历ID，主键
    file_name     TEXT    NOT NULL,                  -- 上传文件名（含扩展名）
    file_type     TEXT    NOT NULL,                  -- 文件类型：pdf / docx
    file_size     INTEGER NOT NULL DEFAULT 0,        -- 文件大小（字节）
    raw_text      TEXT,                              -- 解析出的纯文本（大字段，列表页不返回）
    parse_status  TEXT    NOT NULL DEFAULT 'pending',-- 解析状态：pending/processing/done/failed
    parse_error   TEXT,                              -- 解析失败原因（成功为NULL）
    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')) -- 上传时间
);

-- 实体抽取结果表：一条简历多个字段，一行一个字段
CREATE TABLE IF NOT EXISTS entities (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- 记录ID
    resume_id     INTEGER NOT NULL REFERENCES resumes(id) ON DELETE CASCADE, -- 所属简历
    field_key     TEXT    NOT NULL,                  -- 字段名：name/degree/school/skill/years/company/title
    field_value   TEXT,                               -- 字段值
    source        TEXT    NOT NULL DEFAULT 'llm',    -- 抽取来源：llm（DeepSeek）/ bert（自训练蒸馏模型）
    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')) -- 抽取时间
);
CREATE INDEX IF NOT EXISTS idx_entities_resume ON entities(resume_id); -- 按简历取全部实体

-- 岗位描述表：一个招聘岗位一行
CREATE TABLE IF NOT EXISTS jds (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- JD ID
    title         TEXT    NOT NULL,                  -- 岗位名称，如"Python后端工程师"
    content       TEXT    NOT NULL,                  -- JD 原文（HR输入，不改动）
    req_json      TEXT,                              -- LLM抽取的结构化要求JSON：{degree, min_years, skills[]}
    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')) -- 创建时间
);

-- 匹配任务表：一次"岗位找候选人"运行一行
CREATE TABLE IF NOT EXISTS match_tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- 任务ID
    jd_id         INTEGER NOT NULL REFERENCES jds(id),         -- 目标岗位
    top_k         INTEGER NOT NULL DEFAULT 10,       -- 召回候选人数
    status        TEXT    NOT NULL DEFAULT 'pending',-- 状态：pending/running/done/failed
    progress      INTEGER NOT NULL DEFAULT 0,        -- 进度 0-100（前端轮询展示）
    error         TEXT,                              -- 失败原因（成功为NULL）
    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')), -- 创建时间
    finished_at   TEXT                               -- 完成时间（未完成为NULL）
);

-- 匹配结果表：任务产出的每条"候选人-岗位"匹配一行
CREATE TABLE IF NOT EXISTS match_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- 记录ID
    task_id       INTEGER NOT NULL REFERENCES match_tasks(id) ON DELETE CASCADE, -- 所属任务
    resume_id     INTEGER NOT NULL REFERENCES resumes(id),     -- 候选人简历
    rank          INTEGER NOT NULL,                  -- 排名（1=最匹配）
    score         REAL    NOT NULL,                  -- 匹配分 0-100
    evidence_json TEXT    NOT NULL DEFAULT '[]',     -- 证据链JSON数组，如["3年Python经验 ✓"]
    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')) -- 生成时间
);
CREATE INDEX IF NOT EXISTS idx_results_task ON match_results(task_id, rank); -- 按任务取排名结果

-- Agent 执行日志表：多Agent每步操作留痕（演示"思考过程"数据源）
CREATE TABLE IF NOT EXISTS agent_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- 日志ID
    task_id       INTEGER,                           -- 关联任务（对话类日志可为NULL）
    agent         TEXT    NOT NULL,                  -- Agent名：调度Agent/解析Agent/匹配Agent
    step          TEXT    NOT NULL,                  -- 步骤名：意图理解/硬过滤/向量检索/交叉打分...
    payload_json  TEXT,                              -- 输入输出摘要JSON
    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')) -- 发生时间
);
CREATE INDEX IF NOT EXISTS idx_logs_task ON agent_logs(task_id); -- 按任务取执行轨迹

-- 用户表（M07 权限模块预留，当前版本不启用）
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT, -- 用户ID
    username      TEXT    NOT NULL UNIQUE,           -- 登录名
    password_hash TEXT    NOT NULL,                  -- 密码哈希（bcrypt，禁止明文）
    role          TEXT    NOT NULL DEFAULT 'hr',     -- 角色：hr/admin
    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')) -- 创建时间
);
