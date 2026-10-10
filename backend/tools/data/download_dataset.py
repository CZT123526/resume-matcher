"""下载公开中文简历 NER 数据集并转成本项目训练语料（算法设计 §2.1/§2.2）。

数据：HF ttxy/resume_ner（BSD-2，源自 luopeixiang/named_entity_recognition，
     3821 训练 / 463 验证 / 477 测试句；CSV 每行 = 空格分隔的字符 + 逗号分隔的 BIOES 标签）。
产出：tools/data/ner_{train,val,test}.jsonl，每行 {"chars": [...], "tags": ["B-name", ...]}
     标签已 BIOES→BIO、字段映射到 7 字段；映射不到的标签转 O 并计数。

用法（backend 目录下）：
    python tools/data/download_dataset.py            # 走 HF_ENDPOINT（默认 hf-mirror）
    python tools/data/download_dataset.py --repo xxx/yyy
"""
import argparse
import csv
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

from tools.data.label_mapping import map_tag

DATA_DIR = Path(__file__).resolve().parent
RAW_DIR = DATA_DIR / "raw"
DEFAULT_REPO = "ttxy/resume_ner"
FILES = {"train": "train.csv", "val": "dev.csv", "test": "test.csv"}
EXPECTED = {"train": 3821, "val": 463, "test": 477}  # 官方口径，下载后核对


def _endpoint() -> str:
    return os.getenv("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")


def _fetch(url: str) -> bytes:
    import httpx

    last_exc: Exception | None = None
    for attempt in range(4):  # 4 次退避重试（国内网络对大文件不友好）
        try:
            resp = httpx.get(url, timeout=60, follow_redirects=True)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:
            last_exc = exc
            if attempt == 3:
                break
            time.sleep(2 ** attempt)
    raise RuntimeError(f"下载失败（已重试 4 次）: {url} — {last_exc}；"
                       f"也可手动下载放到 {RAW_DIR}/（文件名见 FILES）") from last_exc


def parse_csv(content: bytes) -> tuple[list[dict], dict[str, int], int]:
    """CSV → 句级记录列表；返回 (records, 丢弃统计, 对齐失败跳过数)。

    丢弃按字符次计（映射是标签级：同一实体的每个字符都映射不到，会整段转 O，
    不会出现 B-/I- 残段）。
    """
    text = content.decode("utf-8-sig")
    records: list[dict] = []
    dropped: dict[str, int] = {}
    skipped = 0
    for row in csv.DictReader(io.StringIO(text)):
        chars = (row.get("text") or "").split()
        tags_raw = (row.get("label") or "").split(",")
        if len(chars) != len(tags_raw) or not chars:
            skipped += 1
            continue
        tags: list[str] = []
        for raw in tags_raw:
            raw = raw.strip()
            mapped = map_tag(raw)
            if mapped is None:
                if raw != "O":
                    dropped[raw] = dropped.get(raw, 0) + 1
                tags.append("O")
            else:
                tags.append(mapped)
        records.append({"chars": chars, "tags": tags})
    return records, dropped, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description="下载简历NER数据集并转换")
    ap.add_argument("--repo", default=DEFAULT_REPO, help="HF 数据集 id")
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{_endpoint()}/datasets/{args.repo}/resolve/main"

    for split, fname in FILES.items():
        raw_path = RAW_DIR / fname
        if raw_path.exists() and raw_path.stat().st_size > 1000:
            print(f"[缓存] {split}: {raw_path} 已存在，跳过下载")
        else:
            print(f"[下载] {split} ← {base}/{fname}")
            raw_path.write_bytes(_fetch(f"{base}/{fname}"))

        records, dropped, skipped = parse_csv(raw_path.read_bytes())
        out = DATA_DIR / f"ner_{split}.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        n_ent = sum(1 for r in records for t in r["tags"] if t.startswith("B-"))
        n_field = len({t.split("-")[1] for r in records for t in r["tags"] if t.startswith("B-")})
        print(f"  → {out}: {len(records)} 句（官方 {EXPECTED[split]}）, "
              f"实体 {n_ent} 个 / 覆盖 {n_field} 字段, 丢弃标签 {dropped or '无'}, 对齐跳过 {skipped}")
        if len(records) < EXPECTED[split] * 0.9:
            print(f"  ⚠ 句数明显少于官方口径，请人工核对数据完整性")
    print("\n下一步：python tools/train_ner.py（本机 CPU 可跑但慢，建议 Colab T4，见脚本头部说明）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
