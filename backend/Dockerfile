# 后端镜像（M06）。容器目录布局与仓库一致：
#   /srv/backend/  代码（BACKEND_DIR，db_file 相对它解析）
#   /srv/db/       schema.sql（REPO_ROOT/db，init_db 唯一建表来源）
#   /srv/data/     SQLite + 向量缓存（卷挂载，容器可弃）
# 注意：本机无 Docker，此文件未经实机构建验证（工作日志 T17 有记录）；
# 首次启动首个请求会经 hf-mirror 拉取 bert-base-chinese（约 400MB，进 hf-cache 卷）。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    HF_HUB_DISABLE_XET=1 \
    TOKENIZERS_PARALLELISM=false \
    DB_PATH=/srv/data/resume_matcher.db

WORKDIR /srv

# 依赖层独立（代码改动不触发重装）；torch 单独走 CPU 源
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir "transformers>=4.40"

COPY backend/ /srv/backend/
COPY db/ /srv/db/

VOLUME ["/srv/data", "/root/.cache/huggingface"]

EXPOSE 8000
WORKDIR /srv/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
