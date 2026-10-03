"""撰写模块模型工厂：支持现有 DeepSeek 和 KIMI 环境变量，不输出凭据。"""

import os

from langchain_openai import ChatOpenAI


def create_writing_model(provider: str | None = None, **kwargs):
    provider = (provider or os.getenv("WRITING_MODEL_PROVIDER", "DEEPSEEK")).upper()
    if provider not in {"DEEPSEEK", "KIMI"}:
        raise ValueError("provider 必须为 DEEPSEEK 或 KIMI")
    key = os.getenv(f"{provider}_API_KEY", "").strip()
    if not key:
        raise ValueError(f"缺少 {provider}_API_KEY")
    defaults = {"DEEPSEEK": ("https://api.deepseek.com", "deepseek-chat"),
                "KIMI": ("https://api.moonshot.cn/v1", "kimi-k2.6")}
    base_url, model = defaults[provider]
    options = dict(model=os.getenv(f"{provider}_MODEL", model).strip(), api_key=key,
                   base_url=os.getenv(f"{provider}_BASE_URL", base_url).strip(),
                   temperature=None, timeout=300, max_retries=2)
    options.update(kwargs)
    return ChatOpenAI(**options)
