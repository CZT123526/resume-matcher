"""收集业务简历上的 NER 错例并产出增训语料（T45）。

背景：线上实体来自公开语料（ttxy/resume_ner，3821 句老式简历）微调的 BERT。
业务简历（翻译/电商/机械等口语化模板）上模型有系统性误标——单字公司残渣
（公司：校）、证书当职位（二级笔译）、常识词当技能（公式）等，页面坏词条
同时污染 structured_text（匹配编码输入）。

两步用法（backend 目录下）：
    python tools/collect_ner_hardcases.py --report   # 第一步：扫库（只读）出错误清单
    python tools/collect_ner_hardcases.py            # 第二步：产出增训语料 tools/data/aug/
之后按 train_ner.py 头部的 Colab 流程训练，唯一区别是上传 tools/data/aug/ 三个文件。

语料构成（远程监督，宁缺勿错）：
- 硬负例：高置信误标 span 所在行——行内可信实体按规则锚定打标，误标 span 强制 O；
- 业务域正例：显式字段行（姓名：/求职意向：）与词典/强模式锚定的 span 打标，其余 O；
- val/test 原样复制公开语料（评测集不动，前后指标口径可比）。
只读业务库（SELECT），输出只写 tools/data/aug/。
"""
import argparse
import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from app.svc import ner_rules
from app.svc.ner_rules import (
    _COMPANY_RE, _DEGREE_PATTERNS, _NAME_RE, _SCHOOL_RE, _TITLE_INTENT_RE,
    _TITLE_RE, _YEARS_RES, match_skills,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
AUG_DIR = DATA_DIR / "aug"
MAX_LINE = 80  # 行级语料上限：与训练 max_length=256 字符对齐，超长行宁可丢弃

# 泛词/栏目头黑名单：它们被标成任何实体都是错（宁缺勿错口径下整条按硬错例处理）
_SECTION_STOP = frozenset({
    "基本信息", "教育背景", "教育经历", "工作经验", "工作经历", "工作内容", "工作职责",
    "工作描述", "任职要求", "岗位职责", "项目经历", "项目经验", "校园经历", "社团经历",
    "自我评价", "个人优势", "证书技能", "职业技能", "技能特长", "专业技能", "荣誉奖项",
    "获奖情况", "在校经历", "获得荣誉", "语言能力", "兴趣爱好", "培训经历", "联系方式",
    "技能", "证书", "荣誉", "爱好", "经历", "校", "院", "系", "班", "委", "团", "队", "会",
})
# 证书当职位（T45 高频误标）：语言等级/职业资格是"身份与证书"，不是职位
_TITLE_CERT_RE = re.compile(
    r"[一二三四五六]级[笔口]译|[一二三四五六]级$|普通话|四级|六级|CET|资格证|证书$"
    r"|驾驶证|驾照|计算机[一二三四]级|党员|团员"
)
_SKILL_DICT_LOWER = {k.lower() for k in ner_rules.SKILL_DICT}


def find_span(line: str, value: str) -> tuple[int, int] | None:
    """值在行内的字符区间（含头不含尾）。跨空格聚合的实体值（BERT 字符级拼接
    会在字间插空格）按"去空白折叠"定位，并映射回原行下标。"""
    v = re.sub(r"\s+", "", value)
    if not v:
        return None
    idx_map = [i for i, ch in enumerate(line) if not ch.isspace()]
    collapsed = "".join(line[i] for i in idx_map).lower()
    pos = collapsed.find(v.lower())
    if pos < 0:
        return None
    return idx_map[pos], idx_map[pos + len(v) - 1] + 1


# ---------- 错例判别（detect） ----------

def is_hard_fp(field: str, value: str) -> bool:
    """高置信误标：可直接当训练负例。判据从严，宁可少收不错杀。"""
    v = re.sub(r"\s+", "", value)
    if not v or v in _SECTION_STOP:
        return True
    if field == "company":
        return len(v) <= 2  # 两字以下"公司"必是残渣；带后缀的长值走词典锚定不会进负例
    if field == "title":
        return bool(_TITLE_CERT_RE.search(v))
    if field == "skill":
        # 词典外、纯中文、两字以内——"公式"一类常识词，不是技能
        return not any(c.isascii() for c in v) and len(v) <= 2 and v.lower() not in _SKILL_DICT_LOWER
    return False


# ---------- 行级锚定（anchor） ----------

def anchor_line(line: str) -> list[tuple[str, int, int]]:
    """用运行时同一套高置信规则给一行锚定可信实体区间（字段, 起, 止）。

    锚定器与 ner_rules 完全同源（显式字段行/词典/强模式），保证训练信号
    与线上抽取口径一致；重叠区间保留先出现者。
    """
    raw: list[tuple[str, int, int]] = []

    def put(field: str, span: tuple[int, int] | None) -> None:
        if span:
            raw.append((field, span[0], span[1]))

    if (m := _NAME_RE.search(line)):
        put("name", find_span(line, m.group(1)))
    m = _TITLE_INTENT_RE.search(line) or _TITLE_RE.search(line)
    if m:
        put("title", find_span(line, m.group(1).strip()))
    for kw in match_skills(line):
        put("skill", find_span(line, kw))
    for m in _COMPANY_RE.finditer(line):
        put("company", find_span(line, m.group(1)))
    for m in _SCHOOL_RE.finditer(line):
        s = m.group(1)
        if not re.search(r"(工作|毕业|就读)", s):  # 与规则抽取同一排除口径
            put("school", find_span(line, s))
    for canonical, aliases in _DEGREE_PATTERNS:  # 每行只收第一个学历词
        hit = next((find_span(line, a) for a in aliases if find_span(line, a)), None)
        if hit:
            put("degree", hit)
            break
    for pat in _YEARS_RES:  # 年限锚到"数字+年"
        for m in pat.finditer(line):
            digits = m.group(1)
            s = line.find(digits, m.start())
            if s >= 0:
                e = s + len(digits) + (1 if line[s + len(digits):s + len(digits) + 1] == "年" else 0)
                raw.append(("years", s, e))

    raw.sort(key=lambda x: (x[1], -(x[2] - x[1])))
    kept: list[tuple[str, int, int]] = []
    for f, s, e in raw:
        if s < 0 or e > len(line) or any(not (e <= s2 or s >= e2) for _, s2, e2 in kept):
            continue
        kept.append((f, s, e))
    return kept


def make_record(line: str, anchors: list[tuple[str, int, int]]) -> dict:
    """一行原文 + 锚定区间 → 字符级 BIO 记录（与 ner_*.jsonl 同构）"""
    chars = list(line)
    tags = ["O"] * len(chars)
    for f, s, e in anchors:
        tags[s] = f"B-{f}"
        for i in range(s + 1, e):
            tags[i] = f"I-{f}"
    return {"chars": chars, "tags": tags}


# ---------- 扫库 ----------

def load_corpora() -> tuple[list[dict], dict[int, dict]]:
    """只读业务库：[{resume_id, file_name, raw_text}] 与 {resume_id: [(field, value)]}"""
    from app.db import db_file
    import sqlite3

    conn = sqlite3.connect(f"file:{db_file().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row  # 业务库访问层同款：按列名取值
    try:
        resumes = [
            {"resume_id": r["id"], "file_name": r["file_name"], "raw_text": r["raw_text"] or ""}
            for r in conn.execute(
                "SELECT id, file_name, raw_text FROM resumes WHERE parse_status='done' "
                "AND raw_text IS NOT NULL AND raw_text != ''"
            )
        ]
        ents: dict[int, dict[str, list[str]]] = {}
        for r in conn.execute("SELECT resume_id, field_key, field_value FROM entities"):
            ents.setdefault(r["resume_id"], {}).setdefault(r["field_key"], []).append(r["field_value"] or "")
    finally:
        conn.close()
    return resumes, ents


def scan_report(resumes: list[dict], ents: dict[int, dict[str, list[str]]]) -> dict:
    """错误清单：按字段统计硬错例与可疑值，附高频样例与姓名-文件名对照"""
    hard: Counter = Counter()          # 字段 → 硬错例计数
    samples: dict[str, Counter] = {}   # 字段 → {误标值: 次数}
    name_mismatch: list[tuple[int, str, str]] = []  # (resume_id, 抽出名, 文件名前缀)
    for r in resumes:
        for field, values in ents.get(r["resume_id"], {}).items():
            for v in values:
                if not v.strip():
                    continue
                if is_hard_fp(field, v):
                    hard[field] += 1
                    samples.setdefault(field, Counter())[v] += 1
        m = re.match(r"([一-龥]{2,4})[_\-－]", r["file_name"])
        if m:
            names = ents.get(r["resume_id"], {}).get("name", [])
            if names and names[0] != m.group(1):
                name_mismatch.append((r["resume_id"], names[0], m.group(1)))
    return {"hard": hard, "samples": samples, "name_mismatch": name_mismatch}


# ---------- 语料产出 ----------

def mine_negatives(resumes: list[dict], ents: dict[int, dict[str, list[str]]]) -> tuple[list[dict], Counter]:
    """硬负例：误标 span 所在行，行内可信实体照常锚定、误标 span 保持 O。

    误标 span 恰好压在真实实体上时（残渣「南」⊂ 公司「南京风行数据服务有限公司」）
    不能整段抹 O——那是教模型否认真实体。跳过该行换下一处，只收误标孤立的干净行。
    """
    records: dict[str, dict] = {}  # 行文本去重
    per_field: Counter = Counter()
    for r in resumes:
        lines = r["raw_text"].splitlines()
        for field, values in ents.get(r["resume_id"], {}).items():
            for v in values:
                if not is_hard_fp(field, v):
                    continue
                for line in lines:
                    if len(line.strip()) > MAX_LINE:
                        continue
                    span = find_span(line, v)
                    if span is None:
                        continue
                    anchors = anchor_line(line)
                    if any(a[1] < span[1] and a[2] > span[0] for a in anchors):
                        continue  # 压住真实实体：这行不能当负例，换行
                    if line not in records:
                        records[line] = make_record(line, anchors)
                    per_field[field] += 1
                    break  # 同一误标值每份简历只收一行，防灌水
    return list(records.values()), per_field


def mine_positives(resumes: list[dict], ents: dict[int, dict[str, list[str]]]) -> tuple[list[dict], Counter]:
    """业务域正例：锚定器命中的行整行打标（跳过含硬错例的行，避免自相矛盾的监督信号）"""
    records: dict[str, dict] = {}
    per_field: Counter = Counter()
    for r in resumes:
        bad_spans = {
            (field, v)
            for field, values in ents.get(r["resume_id"], {}).items()
            for v in values if is_hard_fp(field, v)
        }
        taken = 0
        for line in r["raw_text"].splitlines():
            if taken >= 6 or len(line.strip()) > MAX_LINE:  # 每份简历至多 6 行，防长简历灌水
                break
            if any(find_span(line, v) for _, v in bad_spans):
                continue
            anchors = anchor_line(line)
            if not anchors:
                continue
            if line not in records:
                records[line] = make_record(line, anchors)
            taken += 1
            per_field.update(f for f, _, _ in anchors)
    return list(records.values()), per_field


def build(repeat: int, seed: int, max_neg: int, max_pos: int) -> None:
    resumes, ents = load_corpora()
    print(f"[扫库] done 简历 {len(resumes)} 份，实体 {sum(len(v) for m in ents.values() for v in m.values())} 条")

    neg, neg_stat = mine_negatives(resumes, ents)
    pos, pos_stat = mine_positives(resumes, ents)
    rng = random.Random(seed)
    rng.shuffle(neg)
    rng.shuffle(pos)
    neg, pos = neg[:max_neg], pos[:max_pos]
    print(f"[负例] {len(neg)} 行（按字段 {dict(neg_stat)}）")
    print(f"[正例] {len(pos)} 行（按字段 {dict(pos_stat)}）")

    original = [json.loads(x) for x in
                (DATA_DIR / "ner_train.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    aug = (neg + pos) * repeat
    mixed = original + aug
    AUG_DIR.mkdir(parents=True, exist_ok=True)
    with (AUG_DIR / "ner_train.jsonl").open("w", encoding="utf-8") as f:
        for r in mixed:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for split in ("val", "test"):  # 评测集原样复制：前后指标口径可比
        raw = (DATA_DIR / f"ner_{split}.jsonl").read_bytes()
        (AUG_DIR / f"ner_{split}.jsonl").write_bytes(raw)

    stats = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "resumes_scanned": len(resumes),
        "seed": seed, "repeat": repeat,
        "neg_lines": len(neg), "pos_lines": len(pos),
        "neg_by_field": dict(neg_stat), "pos_by_field": dict(pos_stat),
        "original_train": len(original), "augmented_train": len(mixed),
    }
    (AUG_DIR / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[产物] {AUG_DIR}/ner_train.jsonl {len(mixed)} 句（原 {len(original)} + 增训 {len(aug)}），"
          f"val/test 原样复制；stats.json 已记录")


def main() -> int:
    ap = argparse.ArgumentParser(description="收集 NER 错例并产出增训语料")
    ap.add_argument("--report", action="store_true", help="只扫库出错误清单，不写任何文件")
    ap.add_argument("--repeat", type=int, default=2, help="增训语料重复倍数（对抗 3821 句公开语料的量级差）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-neg", type=int, default=1200)
    ap.add_argument("--max-pos", type=int, default=3000)
    args = ap.parse_args()

    resumes, ents = load_corpora()
    if args.report:
        rep = scan_report(resumes, ents)
        print(f"done 简历 {len(resumes)} 份\n")
        total = sum(rep["hard"].values())
        print(f"== 高置信误标（硬错例）合计 {total} 条 ==")
        for field, n in rep["hard"].most_common():
            tops = "、".join(f"{v}×{c}" for v, c in rep["samples"][field].most_common(12))
            print(f"  {field:8s} {n:4d} 条 · 高频：{tops}")
        print(f"\n姓名与文件名不符 {len(rep['name_mismatch'])} 份"
              + ("，样例：" + "；".join(f"简历{rid} 抽出「{n}」文件名「{f}」"
                                       for rid, n, f in rep["name_mismatch"][:5]) if rep["name_mismatch"] else ""))
        return 0

    build(args.repeat, args.seed, args.max_neg, args.max_pos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
