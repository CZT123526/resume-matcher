"""规则版实体抽取（source=rule）——BERT 模型就位前的兜底实现（算法设计 §8 降级预案）。

设计原则：
- 输出与 BERT 版完全同构：[{field_key, field_value, source}]，可无缝切换；
- 只做高置信度规则（显式字段行、强模式），宁缺勿错；
- 值规范化与 BERT 版共用 normalize_value，保证 7 字段口径一致。
"""
import re

# 7 字段全集（与 app/schemas/resume.py ENTITY_KEYS 一致，算法设计 §1）
ENTITY_KEYS_SET = {"name", "degree", "school", "skill", "years", "company", "title"}

# 学历归一表（算法设计 §1：枚举 大专/本科/硕士/博士/其他）
_DEGREE_PATTERNS = [
    ("博士", ("博士", "博士研究生")),
    ("硕士", ("硕士", "硕士研究生", "研究生", "MBA")),
    ("本科", ("本科", "大学本科", "学士学位", "bachelor")),
    ("大专", ("大专", "专科", "高职")),
]

# 技能词典：长词优先匹配，避免 "python" 抢了 "python3" 之类；匹配后统一小写
SKILL_DICT = [
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang", "rust",
    "php", "ruby", "kotlin", "swift", "scala", "r语言", "matlab", "sql", "mysql",
    "postgresql", "redis", "mongodb", "elasticsearch", "kafka", "rabbitmq",
    "fastapi", "flask", "django", "spring", "springboot", "spring boot", "express",
    "react", "vue", "angular", "next.js", "node.js", "html", "css",
    "docker", "kubernetes", "k8s", "linux", "git", "jenkins", "ci/cd",
    "pytorch", "tensorflow", "keras", "sklearn", "scikit-learn", "pandas", "numpy",
    "机器学习", "深度学习", "自然语言处理", "nlp", "计算机视觉", "cv", "大模型", "llm",
    "bert", "transformer", "数据挖掘", "数据分析", "spark", "hadoop", "hive",
    "excel", "powerbi", "tableau", "photoshop",
]

_NAME_RE = re.compile(r"姓名\s*[:：]\s*([一-龥·]{2,4})")
_SCHOOL_RE = re.compile(
    r"([一-龥]{2,12}?(?:大学|学院|学校)|[A-Za-z][A-Za-z\s&\.]{2,30}University)"
)
_TITLE_RE = re.compile(
    r"(?:求职意向|应聘岗位|职位|岗位|担任|任职)\s*[:：]?\s*"
    r"([一-龥A-Za-z/]{2,20}(?:工程师|经理|主管|总监|专员|助理|实习生|"
    r"架构师|分析师|设计师|开发|运营|产品经理|教师|会计|护士|研究员|科学家))"
)
_COMPANY_RE = re.compile(
    r"([一-龥A-Za-z0-9]{2,20}?(?:有限公司|股份有限公司|集团|科技公司|信息技术公司|银行))"
)
# 工作年限：只认带上下文的年限，避免把"3年制大专"误判成经验
_YEARS_RES = [
    re.compile(r"(\d{1,2})\s*年(?:以上)?(?:的)?.{0,4}(?:工作|从业|开发|相关)?经验"),
    re.compile(r"(?:工作|从业|开发)经验\s*[:：]?\s*(\d{1,2})\s*年"),
    re.compile(r"工作年限\s*[:：]?\s*(\d{1,2})\s*年"),
    re.compile(r"经验\s*[:：]?\s*(\d{1,2})\s*年"),
]


def normalize_value(field_key: str, value: str) -> str | None:
    """7 字段统一规范化（算法设计 §1），非法值返回 None 由调用方丢弃"""
    value = (value or "").strip()
    if not value:
        return None
    if field_key == "degree":
        v = value.lower()
        for canonical, aliases in _DEGREE_PATTERNS:
            # 只做"别名出现在值里"单向匹配：反向会把"研究生"误判进"博士研究生"
            if any(a.lower() in v for a in aliases):
                return canonical
        return "其他"
    if field_key == "years":
        digits = re.sub(r"[^\d]", "", value)
        if not digits:
            return None
        n = int(digits)
        return str(min(max(n, 0), 50))
    if field_key == "skill":
        return value.lower().replace(" ", "")
    if field_key == "name":
        return value if 2 <= len(value) <= 4 else None
    return value[:50]


def extract_entities(text: str) -> list[dict[str, str]]:
    """规则抽取入口：输出与 BERT 版同构，source 恒为 rule"""
    entities: list[dict[str, str]] = []

    def add(field_key: str, raw_value: str | None) -> None:
        normalized = normalize_value(field_key, raw_value or "")
        if normalized and not any(
            e["field_key"] == field_key and e["field_value"] == normalized for e in entities
        ):
            entities.append({"field_key": field_key, "field_value": normalized, "source": "rule"})

    # name：只认"姓名："显式字段行（自由文本猜名字错率太高，宁缺勿错）
    m = _NAME_RE.search(text)
    if m:
        add("name", m.group(1))

    # degree：全文找第一个学历词（长别名优先）
    for canonical, aliases in _DEGREE_PATTERNS:
        if any(alias in text.lower() for alias in aliases):
            add("degree", canonical)
            break

    # school：去重取前3个
    schools = []
    for m in _SCHOOL_RE.finditer(text):
        s = m.group(1).strip()
        if s not in schools and not re.search(r"(工作|毕业|就读)", s):
            schools.append(s)
        if len(schools) >= 3:
            break
    for s in schools:
        add("school", s)

    # skill：词典匹配（长词优先），去重取前30
    text_lower = text.lower()
    found = [kw for kw in sorted(SKILL_DICT, key=len, reverse=True) if kw in text_lower]
    for kw in found[:30]:
        add("skill", kw)

    # years：多模式取最大值（多段经历常只写总年限）
    years = [int(m.group(1)) for pat in _YEARS_RES for m in pat.finditer(text)]
    if "应届" in text and not years:
        add("years", "0")
    elif years:
        add("years", str(max(years)))

    # title / company
    m = _TITLE_RE.search(text)
    if m:
        add("title", m.group(1))
    companies = []
    for m in _COMPANY_RE.finditer(text):
        c = m.group(1).strip()
        if c not in companies:
            companies.append(c)
        if len(companies) >= 3:
            break
    for c in companies:
        add("company", c)

    return entities
