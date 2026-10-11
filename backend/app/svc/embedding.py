"""S05 文本语义编码：BERT mean pooling（主路）→ TF-IDF 字符n-gram（降级）。

两级实现同一接口 encode(texts) -> 归一化矩阵：
- BERT：bert-base-chinese（HF 缓存，本地推理，零 API）；
- TF-IDF：无 torch/模型环境时兜底，词表与 IDF 随向量缓存持久化保证
  建库与查询同一特征空间（否则 JD 查询向量与简历库不可比）。

env FORCE_TFIDF=1 可强制降级路径（单测提速用）。
"""
import logging
import os
import re
from collections import Counter
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_BERT_MODEL = "bert-base-chinese"
_CHAR_RE = re.compile(r"[一-龥a-z0-9]+")

_bert_model = None
_bert_tried = False


class _BertEncoder:
    """BERT mean pooling（算法设计 §3.2），L2 归一化"""

    kind = "bert"

    def __init__(self):
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from transformers import AutoModel, AutoTokenizer

        import torch

        self._torch = torch
        # 权重已在本地缓存时强制离线加载——运行时本就全本地，联网探测
        # 在无代理环境会拖到超时（曾致误降级 TF-IDF）；缓存未命中才走网络下载
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(_BERT_MODEL, local_files_only=True)
            self.model = AutoModel.from_pretrained(_BERT_MODEL, local_files_only=True)
        except OSError:
            self.tokenizer = AutoTokenizer.from_pretrained(_BERT_MODEL)
            self.model = AutoModel.from_pretrained(_BERT_MODEL)
        self.model.eval()

    def encode(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        torch = self._torch
        out = []
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                enc = self.tokenizer(
                    batch, padding=True, truncation=True, max_length=256, return_tensors="pt"
                )
                hidden = self.model(**enc).last_hidden_state          # (B, L, H)
                mask = enc["attention_mask"].unsqueeze(-1).float()    # (B, L, 1)
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                out.append(pooled.cpu().numpy().astype(np.float32))
        return _l2norm(np.vstack(out))


class _TfidfEncoder:
    """字符 2/3-gram TF-IDF 降级实现（纯 numpy，离线零依赖）"""

    kind = "tfidf"

    def __init__(self, vocab: dict[str, int] | None = None, idf: np.ndarray | None = None):
        self.vocab = vocab or {}
        self.idf = idf

    def fit(self, corpus: list[str]) -> "_TfidfEncoder":
        df: Counter = Counter()
        for doc in corpus:
            df.update(set(self._grams(doc)))
        # 词表：出现于 ≥2 篇或词表太小（<200 样本场景放宽为 ≥1）
        min_df = 2 if len(corpus) >= 200 else 1
        terms = sorted(t for t, c in df.items() if c >= min_df)
        self.vocab = {t: i for i, t in enumerate(terms)}
        n = len(corpus)
        self.idf = np.log((1 + n) / (1 + np.array([df[t] for t in terms], dtype=np.float32))) + 1.0
        return self

    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        mat = np.zeros((len(texts), len(self.vocab)), dtype=np.float32)
        for row, doc in enumerate(texts):
            for g, c in Counter(self._grams(doc)).items():
                col = self.vocab.get(g)
                if col is not None:
                    mat[row, col] = (1 + np.log(c)) * self.idf[col]
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        return mat / np.clip(norms, 1e-9, None)

    @staticmethod
    def _grams(doc: str) -> list[str]:
        tokens = _CHAR_RE.findall(doc.lower())
        joined = " ".join(tokens)
        grams = [joined[i : i + 2] for i in range(len(joined) - 1)]
        grams += [joined[i : i + 3] for i in range(len(joined) - 2)]
        return grams


def get_encoder() -> _BertEncoder | _TfidfEncoder:
    """进程内单例：优先 BERT；无 torch/模型或 FORCE_TFIDF=1 时降级 TF-IDF"""
    global _bert_model, _bert_tried
    if os.getenv("FORCE_TFIDF") == "1":
        return _TfidfEncoder()  # fit 由向量缓存层负责
    if not _bert_tried:
        _bert_tried = True
        try:
            _bert_model = _BertEncoder()
            logger.info("语义编码使用 BERT（%s）", _BERT_MODEL)
        except Exception as exc:
            logger.warning("BERT 不可用，降级 TF-IDF 编码: %s", exc)
    return _bert_model if _bert_model is not None else _TfidfEncoder()


def save_tfidf_state(encoder: _TfidfEncoder, state_file: Path) -> None:
    """持久化词表+IDF（降级模式下建库与查询共用）"""
    import json

    np.savez_compressed(state_file, idf=encoder.idf)
    state_file.with_suffix(".vocab.json").write_text(
        json.dumps(encoder.vocab, ensure_ascii=False), encoding="utf-8"
    )


def load_tfidf_state(state_file: Path) -> _TfidfEncoder | None:
    import json

    if not state_file.exists():
        return None
    data = np.load(state_file)
    vocab = json.loads(state_file.with_suffix(".vocab.json").read_text(encoding="utf-8"))
    return _TfidfEncoder(vocab=vocab, idf=data["idf"])


def _l2norm(mat: np.ndarray) -> np.ndarray:
    return mat / np.clip(np.linalg.norm(mat, axis=1, keepdims=True), 1e-9, None)
