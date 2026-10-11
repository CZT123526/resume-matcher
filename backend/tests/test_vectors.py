"""向量缓存编码器指纹测试（T25 教训：换编码器后旧缓存不得复用）。"""
import json


def test_legacy_vector_meta_invalidated(tmp_path, monkeypatch):
    """旧版缓存元数据无 encoder 字段 → 视为指纹不匹配，必须触发重建"""
    from app.svc import vectors

    ids = tmp_path / "resume_ids.json"
    ids.write_text(json.dumps({"order": [1], "hashes": {1: "x"}}), encoding="utf-8")
    monkeypatch.setattr(vectors, "IDS_FILE", ids)
    assert vectors._load_meta()["encoder"] == ""


def test_encoder_fingerprint_changes_with_model(monkeypatch):
    """编码器指向不同模型 → 指纹不同（同 hash 缓存也会失效重建）"""
    from app.svc import vectors
    import app.svc.embedding as emb

    monkeypatch.setattr(emb, "_BERT_MODEL", "/tmp/domain_model")
    fp_a = vectors._encoder_fingerprint()
    monkeypatch.setattr(emb, "_BERT_MODEL", "bert-base-chinese")
    fp_b = vectors._encoder_fingerprint()
    assert fp_a != fp_b
    assert "/tmp/domain_model" in fp_a and "bert-base-chinese" in fp_b
