"""对照组二：DeepSeek 零样本打分（算法设计 §7，仅离线实验用，绝不进 backend/app/）。

红线：本文件只存在于 tools/baselines/，运行时链路零外部 API（TC-API-01）。
Key 从环境变量 DEEPSEEK_API_KEY 读取（可写入 backend/.env，已在 .gitignore）；
无 key 时 available()=False，评测脚本干净跳过该组。

稳健性（文档 §7）：3 次指数退避重试；结果 jsonl 缓存去重（同对 JD/简历不二次付费）；
单条最终失败记 None，不中断整批。
"""
import hashlib
import json
import os
import time
from pathlib import Path

# 显式加载 backend/.env（key 只放这里，已被 .gitignore 排除）；
# 不依赖任何 app.* 的间接 import 顺序
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

CACHE_FILE = Path(__file__).with_name("deepseek_cache.jsonl")
DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")  # 官方别名，恒指向最新版
API_URL = "https://api.deepseek.com/chat/completions"

_PROMPT = """你是招聘评估专家。给定岗位描述(JD)与候选人简历文本，评估该候选人与岗位的匹配程度。
只输出一个 JSON 对象，格式：{{"score": 数字}}，score 取 0.0~1.0（1 为完全匹配，0 为完全不匹配），不要输出任何其他文字。

JD：
{jd}

简历：
{resume}"""


def _cache_key(model: str, jd_text: str, resume_text: str) -> str:
    raw = json.dumps([model, jd_text, resume_text], ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _load_cache() -> dict[str, float]:
    if not CACHE_FILE.exists():
        return {}
    cache = {}
    for line in CACHE_FILE.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            cache[item["key"]] = item["score"]
        except (json.JSONDecodeError, KeyError):
            continue  # 半行/坏行跳过，缓存仍然可用
    return cache


class DeepSeekScorer:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = model or DEFAULT_MODEL
        self._cache = _load_cache()

    def available(self) -> bool:
        return bool(self.api_key)

    def score(self, jd_text: str, resume_text: str) -> float | None:
        """0.0~1.0；网络/解析最终失败返回 None（不计入该对的评测）"""
        if not self.api_key:
            return None
        key = _cache_key(self.model, jd_text, resume_text)
        if key in self._cache:
            return self._cache[key]

        import httpx

        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": _PROMPT.format(jd=jd_text[:2000], resume=resume_text[:2000])}
            ],
            "temperature": 0.0,
            "max_tokens": 64,
        }
        for attempt in range(3):  # 3 次退避重试
            try:
                resp = httpx.post(
                    API_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=60,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                score = self._parse_score(content)
                self._cache[key] = score
                with CACHE_FILE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"key": key, "score": score}, ensure_ascii=False) + "\n")
                return score
            except Exception:
                if attempt == 2:
                    return None
                time.sleep(2 ** attempt)  # 1s, 2s
        return None

    @staticmethod
    def _parse_score(content: str) -> float:
        """容错解析：取首个 JSON 对象的 score，越界截断到 [0,1]"""
        text = content.strip()
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            data = json.loads(text[start : end + 1])
            return round(min(max(float(data["score"]), 0.0), 1.0), 4)
        raise ValueError(f"无法从响应解析 score: {content[:100]}")
