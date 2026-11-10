"""T55 简历风控体检：四类规则检测，输出结构化 findings 供人工复核（API-22）。

免责口径（写进界面与文档）：系统只能暴露文本中的矛盾点，技术上无法判定简历真假，
提示仅供人工复核，不构成造假判定。

四类检测（docs/算法设计.md §风控规则；③默认关闭，见下）：
1. 时间线矛盾（risk）：从 raw_text 正则提取经历起止段（YYYY.MM / YYYY/MM / YYYY-MM /
   至今，形状同 ner._DATE_RANGE_RE），段间重叠或段内倒序 → risk。能解析出 ≥2 段才检
   重叠（单段自倒序 1 段即可判）；不足不出行。
2. 技能脱节（warn）：skill 实体值经 _skill_present（B1 全项目唯一「词在不在」实现）
   在经历行查不到 → warn。经历行复用 vectors._work_lines（"姓名：/电话：" 字段行已被
   结构性排除，技能清单行"技能：X"也带冒号不入选——查的就是"经历正文有没有支撑"）。
3. 疑似克隆（warn，**默认关闭** RISK_CLONE_ENABLED=0）：简历向量与业务投递池
   （source='business'）近邻点积 ≥0.98 且姓名实体不同。关闭原因（用户拍板）：真库
   business 标签混入 1050 份评测语料（模板孪生相似度 1.0，全库 0.98 实测 38052 对），
   比对池语义不成立；语料标签正名（数据迁移）后置 1 启用。实现完整保留：
   只读 load_cache()，绝不内联 ensure_cache 重建（真库 BERT 全量重建分钟级会卡死
   请求；重建由匹配/反向推荐等后台链路负责），缓存不可得整项如实跳过。
4. 联系方式格式异常（warn）：以 1 开头的 10~12 位数字串若不符合手机号形状
   （1[3-9] 开头恰好 11 位，与 T54 打码正则同源判断）→ warn。合法号码不提示。

纪律「信息不足不出行」（T49/T50 同口径）：证据凑不齐的检查项直接缺席，findings 里
不出现"未能检测"之类的占位行。全部通过 → 单条 ok 总述。

零外部 API（TC-API-01 红线）；本模块只读业务库，不写任何表。
"""
import datetime
import logging
import re

import numpy as np

from app.config import settings
from app.core.errors import AppError, ErrorCode
from app.db import get_db
from app.svc.ner_rules import _skill_present
from app.svc.vectors import _work_lines, load_cache

logger = logging.getLogger(__name__)

# ---------- 时间线 ----------
# 日期段形状：与 ner._DATE_RANGE_RE 同族（YYYY.MM / YYYY/MM / YYYY-MM）
_DATE = r"\d{4}[./-]\d{1,2}"
# 起止对：段 - 段 / 段 ~ 段 / 段 至 至今 / 段 — 至今（分隔符 1~2 字符）
_RANGE_RE = re.compile(rf"({_DATE})\s*(?:[-—–~]|至|到)\s*({_DATE}|至今)")


def _month_index(s: str) -> int:
    """'2023.06' → 年*12+月 的可比整数"""
    y, m = re.split(r"[./-]", s)
    return int(y) * 12 + int(m)


def _timeline_findings(raw_text: str) -> list[dict]:
    """时间线矛盾：重叠 / 倒序。解析不足 2 段且无自倒序时不出行。"""
    spans = [(m.group(1), m.group(2)) for m in _RANGE_RE.finditer(raw_text)]
    # 同一起止段重复出现只算一段（正文与表格里各抄一遍不构成矛盾）
    uniq: list[tuple[str, str]] = []
    for ab in spans:
        if ab not in uniq:
            uniq.append(ab)

    evidence: list[str] = []
    # 倒序：单段自身结束早于开始（1 段即可判）
    for a, b in uniq:
        if b != "至今" and _month_index(b) < _month_index(a):
            evidence.append(f"{a}-{b}（结束早于开始）")
    # 重叠：≥2 段才可判；"至今" 视为无限延伸
    parsed = [
        (a, b, _month_index(a), None if b == "至今" else _month_index(b))
        for a, b in uniq
    ]
    for i in range(len(parsed)):
        ai, bi, si, ei = parsed[i]
        hi_i = float("inf") if ei is None else ei
        for j in range(i + 1, len(parsed)):
            aj, bj, sj, ej = parsed[j]
            hi_j = float("inf") if ej is None else ej
            if si <= hi_j and sj <= hi_i:
                evidence.append(f"{ai}-{bi} 与 {aj}-{bj} 时间重叠")
    if not evidence:
        return []
    return [{
        "level": "risk",
        "text": "经历时间线存在矛盾（重叠或倒序）",
        "evidence": "；".join(dict.fromkeys(evidence[:3])),
    }]


# ---------- 技能脱节 ----------
def _skill_gap_findings(raw_text: str, skills: list[str]) -> list[dict]:
    """技能脱节：技能清单里写了、经历正文里找不到（单字符值判定不可靠，跳过）。"""
    work_text = "\n".join(_work_lines(raw_text)).lower()
    if not work_text or not skills:
        return []  # 信息不足不出行：没有经历行可比对，硬说"脱节"是冤枉人
    out = []
    for kw in skills:
        v = (kw or "").strip()
        if len(v) < 2:
            continue
        if not _skill_present(v, work_text):
            out.append({"level": "warn", "text": f"技能 {v} 无经历描述支撑"})
    return out


# ---------- 疑似克隆 ----------
_CLONE_THRESHOLD = 0.98  # 业务投递池内比对；阈值定界见 docs/算法设计.md §风控规则


def _business_ids() -> set[int]:
    """业务投递池 id 集（source 列判，NULL 由 COALESCE 按业务兜底——T53 同口径）"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id FROM resumes WHERE COALESCE(source,'business')='business'"
        ).fetchall()
    finally:
        conn.close()
    return {r["id"] for r in rows}


def _clone_finding(resume_id: int, name_of: dict[int, str]) -> dict | None:
    """与业务投递池近邻点积 ≥0.98 且姓名不同 → 疑似重复投递；不可得则如实跳过。

    只读 load_cache()，绝不内联 ensure_cache——视图端点触发分钟级重建会把请求卡死。
    比对池限定业务投递（source='business'）：评测语料是模板生成数据，天然近重复
    （真库实测 ≥0.98 对数 3.8 万、p50 最近邻=1.0），混入比对池检查就失去意义。
    """
    cached = load_cache()
    if cached is None:
        logger.info("风控克隆检测：向量缓存不可用（未建库或已失效），该项跳过")
        return None
    matrix, order = cached
    if resume_id not in order:
        return None
    biz = _business_ids()
    pool = [rid for rid in order if rid != resume_id and rid in biz]
    if not pool:
        return None
    pos_of = {rid: k for k, rid in enumerate(order)}
    sims = matrix[[pos_of[rid] for rid in pool]] @ matrix[pos_of[resume_id]]
    j = int(np.argmax(sims))
    if float(sims[j]) < _CLONE_THRESHOLD:
        return None
    other = pool[j]
    mine, theirs = name_of.get(resume_id, ""), name_of.get(other, "")
    if not mine or not theirs or mine == theirs:
        return None  # 姓名一致更像同一人多份版本，不作克隆提示
    return {
        "level": "warn",
        "text": f"与《{theirs}》相似度 {float(sims[j]):.2f}，疑似重复投递",
        "evidence": f"resume_id={other}，余弦相似度 {float(sims[j]):.4f} ≥ 阈值 {_CLONE_THRESHOLD}",
    }


# ---------- 联系方式格式 ----------
# 疑似手机号的更宽网：1 开头 10~12 位（合法形状是恰好 11 位且第 2 位 3-9）
_SUSPECT_PHONE_RE = re.compile(r"(?<!\d)1\d{9,11}(?!\d)")
_VALID_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def _phone_findings(raw_text: str) -> list[dict]:
    """联系方式格式异常：落入宽网但不符合合法手机号形状的号码。"""
    out = []
    seen: set[str] = set()
    for m in _SUSPECT_PHONE_RE.finditer(raw_text):
        num = m.group(0)
        if num in seen or _VALID_PHONE_RE.fullmatch(num):
            continue
        seen.add(num)
        out.append({
            "level": "warn",
            "text": f"联系方式 {num} 格式异常（手机号应为 1[3-9] 开头的 11 位数字）",
            "evidence": num,
        })
    return out


def _load_resume(resume_id: int) -> tuple[str, list[str], dict[int, str]]:
    """(raw_text, 技能实体值列表, {resume_id: 姓名实体值}——姓名表含全库，供克隆比对)"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT parse_status, raw_text FROM resumes WHERE id=?", (resume_id,)
        ).fetchone()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, f"简历 {resume_id} 不存在")
        if row["parse_status"] != "done":
            raise AppError(
                ErrorCode.BAD_PARAM,
                f"简历 {resume_id} 尚未解析完成（状态 {row['parse_status']}），无法体检",
            )
        skill_rows = conn.execute(
            "SELECT field_value FROM entities WHERE resume_id=? AND field_key='skill' ORDER BY id",
            (resume_id,),
        ).fetchall()
        name_rows = conn.execute(
            "SELECT resume_id, field_value FROM entities WHERE field_key='name'"
        ).fetchall()
    finally:
        conn.close()
    return (
        row["raw_text"] or "",
        [r["field_value"] for r in skill_rows],
        {int(r["resume_id"]): r["field_value"] for r in name_rows},
    )


def risk_check(resume_id: int) -> dict:
    """风控体检主入口：四类检测 + 总述。findings 有内容才逐条列出，全绿只给一条 ok。"""
    raw_text, skills, name_of = _load_resume(resume_id)

    findings: list[dict] = []
    findings += _timeline_findings(raw_text)
    findings += _skill_gap_findings(raw_text, skills)
    if settings.RISK_CLONE_ENABLED:  # 默认关（语料标签污染，正名后启用），见模块 docstring ③
        clone = _clone_finding(resume_id, name_of)
        if clone:
            findings.append(clone)
    findings += _phone_findings(raw_text)

    if not findings:
        findings = [{"level": "ok", "text": "未发现明显矛盾点"}]
        summary = "未发现明显矛盾点"
    else:
        n_risk = sum(1 for f in findings if f["level"] == "risk")
        n_warn = sum(1 for f in findings if f["level"] == "warn")
        parts = []
        if n_risk:
            parts.append(f"{n_risk} 项风险信号")
        if n_warn:
            parts.append(f"{n_warn} 项提示")
        summary = f"发现 {'、'.join(parts)}，建议人工复核"
    return {
        "resume_id": resume_id,
        "findings": findings,
        "summary": summary,
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
