"""S01–S11 服务层契约：签名即契约（对应 docs/status/svc.md）。

用法：认领模块后，把对应函数复制/移入 svc/ 下的实现文件补全实现；
禁止改动签名与语义——需要变更时先改 docs/status/svc.md 和本文件，
再改实现（契约先行）。

红线：本文件及 svc/ 所有实现禁止任何外部 HTTP API 调用；
DeepSeek 基线只允许出现在 backend/tools/（S09 的实现位置在 tools/）。
"""
from typing import Any, BinaryIO

import numpy as np

# ---------------------------------------------------------------------------
# M01 数据预处理与实体抽取
# ---------------------------------------------------------------------------


def parse_document(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """S01 解析简历文件为纯文本。

    入参: file_bytes 文件二进制; filename 原始文件名（判断扩展名）。
    出参: {"text": str} 纯文本（页数等元信息无消费方，不出契约）。
    异常: AppError(E4002) 扩展名不支持; AppError(E4001) 文件损坏/无法解析。
    实现: svc/parsing.py（M01）
    """
    raise NotImplementedError("S01 待实现，认领见 docs/status/svc.md")


def extract_entities_bert(text: str) -> list[dict[str, str]]:
    """S02 BERT NER 实体抽取。

    入参: text 简历纯文本。
    出参: [{"field_key": "name", "field_value": "张三"}, ...]
          field_key ∈ ENTITY_KEYS（见 app/schemas/resume.py），
          同一字段多值时输出多条（如多个 skill）。
    实现: svc/ner.py（M01）
    """
    raise NotImplementedError("S02 待实现")


def train_ner(data_dir: str, output_dir: str) -> dict[str, float]:
    """S03 训练 NER 模型（在 Colab T4 上跑，CPU 机器不执行）。

    入参: data_dir 标注数据目录; output_dir 模型产物目录（backend/models/ner/）。
    出参: {"f1": float, "precision": float, "recall": float}（测试集实体级）
    训练配置: 见 docs/算法设计.md §2。
    实现: backend/tools/train_ner.py（M01）
    """
    raise NotImplementedError("S03 待实现")


# ---------------------------------------------------------------------------
# M02 岗位-候选人语义匹配
# ---------------------------------------------------------------------------


def build_jd_requirements(jd_text: str) -> dict[str, Any]:
    """S04 JD 结构化要求抽取（规则 + NER 离线组合，无外部 API）。

    入参: jd_text JD 原文。
    出参: {"degree": "本科" | None, "min_years": int | None, "skills": [str, ...]}
    实现: svc/jd_parsing.py（M02）
    """
    raise NotImplementedError("S04 待实现")


def embed_texts(texts: list[str]) -> np.ndarray:
    """S05 文本向量化（BERT 语义编码，M02）。

    入参: texts 文本数组。
    出参: 归一化向量矩阵 shape=(len(texts), hidden_size)，dtype=float32。
    纪律: 批量编码、CPU 推理；结果缓存见 docs/technical.md D2（vectors.npy）。
    实现: svc/embedding.py
    """
    raise NotImplementedError("S05 待实现")


def cosine_rank(jd_vector: np.ndarray, top_k: int) -> list[dict[str, Any]]:
    """S06 岗位向量 × 简历向量矩阵 余弦相似度排序取 Top-K。

    入参: jd_vector 单条岗位向量; top_k 返回条数。
    出参: [{"resume_id": int, "score": float(0~1, 4位小数)}, ...] 按 score 降序。
    实现: svc/ranking.py（M02）
    """
    raise NotImplementedError("S06 待实现")


def compute_evidence(jd_reqs: dict[str, Any], resume_entities: list[dict[str, str]]) -> list[str]:
    """S07 生成证据链文本（只解释、不改分数——打分与解释分离）。

    入参: jd_reqs S04 输出; resume_entities 该简历的实体列表。
    出参: ["技能重叠: Python/FastAPI (2/2)", "学历满足: 硕士≥本科", ...]
    规则: 见 docs/算法设计.md §4。
    实现: svc/evidence.py（M02）
    """
    raise NotImplementedError("S07 待实现")


# ---------------------------------------------------------------------------
# M04 离线评测与多模型对比
# ---------------------------------------------------------------------------


def tfidf_baseline(jd_text: str, resume_texts: list[str]) -> list[float]:
    """S08 对照组一：TF-IDF + 余弦相似度（无深度模型）。

    出参: 与 resume_texts 等长的相似度数组（0~1）。
    实现: backend/tools/baselines/tfidf_baseline.py（M04）
    """
    raise NotImplementedError("S08 待实现")


def deepseek_zeroshot(jd_text: str, resume_text: str) -> dict[str, Any]:
    """S09 对照组二：DeepSeek 零样本打分。

    ⚠️ 实现位置强制在 backend/tools/baselines/，禁止 import 进 backend/app/。
    入参: jd_text / resume_text。
    出参: {"score": float, "reason": str}（原始返回 + 解析结果）
    纪律: 带重试与结果缓存，失败降级为 None 不中断评测。
    实现: backend/tools/baselines/deepseek_zeroshot.py（M04）
    """
    raise NotImplementedError("S09 待实现（注意：只能写在 tools/）")


def evaluate(run_files: list[str], gold_file: str) -> dict[str, Any]:
    """S10 统一评测入口：算指标 + 出图表。

    入参: run_files 各方法输出文件; gold_file 金标准文件。
    出参: {"ndcg@10": float, "f1": float, "latency_p95_ms": float, ...}
          图表写入 docs/eval/。
    协议: 见 docs/算法设计.md §6-§7（同一测试集、固定种子）。
    实现: backend/tools/evaluate.py（M04）
    """
    raise NotImplementedError("S10 待实现")


# ---------------------------------------------------------------------------
# M05 评估报告导出
# ---------------------------------------------------------------------------


def generate_report(task_id: int) -> BinaryIO:
    """S11 生成 PDF 评估报告。

    出参: PDF 文件二进制流（api 层以 FileResponse 返回）。
    实现: svc/report.py（M05, P1）
    """
    raise NotImplementedError("S11 待实现（P1）")
