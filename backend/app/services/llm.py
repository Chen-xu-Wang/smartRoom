"""LLM 客户端 —— 接入真实大模型（OpenAI 兼容协议）.

替代原 agent.py 里关键词规则的意图理解与工单分析。
所有配置来自 app.config（读自 backend/.env 的 LLM_* 变量）。

设计要点：
    - 用标准库 urllib，不引入额外依赖（requests/httpx 不一定装在 venv 里）
    - 调用失败 / 超时 / 返回非 JSON 时一律抛异常，由调用方 fallback 到原规则逻辑
    - 不做任何兜底「脑补」，保证「模型没返回就按原规则走」
"""
import json
import urllib.request
import urllib.error
from ..config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL


def is_llm_enabled() -> bool:
    """是否已配置真实大模型（key 与 base url 都非空才算启用）。"""
    return bool(LLM_API_KEY and LLM_BASE_URL)


def _chat(messages: list, temperature: float = 0.3, timeout: int = 90, model: str = None) -> str:
    """调用 /chat/completions，返回助手消息 content 字符串。失败抛异常。"""
    if not is_llm_enabled():
        raise RuntimeError("LLM 未配置（LLM_API_KEY / LLM_BASE_URL 缺失）")

    model = model or LLM_MODEL
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {LLM_API_KEY}")

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")

    obj = json.loads(body)
    return obj["choices"][0]["message"]["content"]


def chat_json(messages: list, temperature: float = 0.3, timeout: int = 90, model: str = None) -> dict:
    """调用大模型并把返回解析为 JSON dict。

    容错：模型可能在 JSON 外包 ```json 代码块或加解释文字，
    这里取「第一个 {」到「最后一个 }」之间的内容再 json.loads。
    """
    content = _chat(messages, temperature=temperature, timeout=timeout, model=model)
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"LLM 未返回可解析的 JSON：{content[:200]}")
    return json.loads(content[start:end + 1])
