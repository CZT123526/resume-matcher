"""PII 打码（T54）：手机号 / 邮箱 / 身份证。

口径（docs/api-schemas.md §5 打码口径）：
- 手机号 `1[3-9]` 开头 11 位 → 前 3 + **** + 后 4（138****1234）
- 邮箱 → 用户名前 2 位 + ***@域名（zh***@163.com）
- 身份证 18 位 → 前 4 + 12 个 * + 后 2（保长，防下游按长度断言炸掉）

应用点：详情 /resumes/{id} 与 /data 视图的 raw_text 默认打码（?reveal=1 显示
原文并记审计）；搜索 snippet 强制打码不可 reveal（防列表页泄露）。
"""

import re

# 手机号：1[3-9] 开头 11 位，前后不能还是数字（防把长数字串里的 11 位截出来）
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 邮箱：常规用户名@域名
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 身份证：18 位（末位可为 X），前后不能还是数字
_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")


def _mask_email(m: re.Match) -> str:
    user, _, domain = m.group(0).partition("@")
    head = user[:2] if len(user) >= 2 else user[:1]
    return f"{head}***@{domain}"


def mask_pii(text: str | None) -> str | None:
    """打码一段文本；空值原样返回。

    替换顺序有讲究：先邮箱（否则 `13812345678@163.com` 会被手机号规则
    截成 `138****5678@163.com`，邮箱规则就匹配不上了）→ 再身份证 → 再手机号。
    """
    if not text:
        return text
    text = _EMAIL_RE.sub(_mask_email, text)
    text = _ID_RE.sub(lambda m: m.group(0)[:4] + "*" * 12 + m.group(0)[-2:], text)
    text = _PHONE_RE.sub(lambda m: m.group(0)[:3] + "****" + m.group(0)[-4:], text)
    return text
