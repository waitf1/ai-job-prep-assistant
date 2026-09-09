from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv(override=True)


@dataclass(frozen=True)
class LLMSettings:
    """Runtime settings for the OpenAI-compatible LLM provider."""

    base_url: str
    api_key: str
    model: str
    temperature: float = 0.2
    timeout_seconds: float = 60.0
    max_retries: int = 2
    max_input_chars: int = 100000


def get_llm_settings() -> LLMSettings:
    """Load LLM settings from environment variables."""

    return LLMSettings(
        base_url=os.getenv("LLM_BASE_URL", "").strip(),
        api_key=os.getenv("LLM_API_KEY", "").strip(),
        model=os.getenv("LLM_MODEL", "qwen-plus").strip(),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
        timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        max_input_chars=int(os.getenv("LLM_MAX_INPUT_CHARS", "100000")),
    )
