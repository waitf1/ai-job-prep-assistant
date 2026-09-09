from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse
from ipaddress import ip_address

import httpx
import logging
import math
import hashlib
import json
import time
import uuid
from collections import deque

from langchain_openai import ChatOpenAI

from app.config import LLMSettings, get_llm_settings


class LLMConfigError(RuntimeError):
    """Raised when the LLM provider is not configured correctly."""


@dataclass(frozen=True)
class ToolChatResponse:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


CALL_RECORDS = deque(maxlen=200)
logger = logging.getLogger("job_prep.llm")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False


class LLMClient:
    """Small wrapper around an OpenAI-compatible chat model.

    OneAI / OneAPI can be used here as long as it exposes an OpenAI-compatible
    base URL, API key, and model name.
    """

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or get_llm_settings()
        self._validate_settings()
        transport_options = {}
        hostname = urlparse(self.settings.base_url).hostname or ""
        try:
            is_loopback = ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = hostname.lower() == "localhost"
        if is_loopback:
            # Streamlit may inherit proxy variables from its launching terminal.
            # A local OneAPI server must be reached directly in both SDK clients.
            transport_options = {
                "http_client": httpx.Client(trust_env=False),
                "http_async_client": httpx.AsyncClient(trust_env=False),
                "openai_proxy": "",
            }
        self.model = ChatOpenAI(
            base_url=self.settings.base_url,
            api_key=self.settings.api_key,
            model=self.settings.model,
            temperature=self.settings.temperature,
            timeout=self.settings.timeout_seconds,
            max_retries=self.settings.max_retries,
            **transport_options,
        )

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """Send a simple system/user message pair and return text content."""

        response = self._invoke(self.model,
            [
                ("system", system_prompt),
                ("human", user_prompt),
            ]
        )
        return self._stringify_content(response.content)

    def chat_with_tools(self, system_prompt: str, user_prompt: str, tools: list[dict]) -> ToolChatResponse:
        response = self._invoke(self.model.bind_tools(tools),
            [
                ("system", system_prompt),
                ("human", user_prompt),
            ]
        )
        return ToolChatResponse(
            content=self._stringify_content(response.content),
            tool_calls=getattr(response, "tool_calls", []) or [],
        )

    def _invoke(self, model, messages):
        # Log metadata only: never prompts, responses, URLs, keys or exception text.
        record = {"call_id": uuid.uuid4().hex, "model": self.settings.model,
                  "input_chars": sum(len(text) for _, text in messages), "success": False,
                  "prompt_version": hashlib.sha256(messages[0][1].encode()).hexdigest()[:12]}
        started = time.perf_counter()
        try:
            if record["input_chars"] > self.settings.max_input_chars:
                raise ValueError("本次输入超过长度预算，请减少资料或回答长度后重试。")
            response = model.invoke(messages)
            usage = getattr(response, "usage_metadata", None) or {}
            provider = (getattr(response, "response_metadata", None) or {}).get("token_usage", {}) or {}
            for output, modern, legacy in (("input_tokens", "input_tokens", "prompt_tokens"),
                                            ("output_tokens", "output_tokens", "completion_tokens")):
                value = usage.get(modern, provider.get(legacy))
                record[output] = value if type(value) is int and value >= 0 else None
            record["success"] = True
            return response
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            raise
        finally:
            record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
            CALL_RECORDS.append(record)
            logger.info("llm_call %s", json.dumps(record, ensure_ascii=False))

    def _validate_settings(self) -> None:
        if not math.isfinite(self.settings.timeout_seconds) or self.settings.timeout_seconds <= 0 or not 0 <= self.settings.max_retries <= 5 or self.settings.max_input_chars <= 0:
            raise LLMConfigError("超时和输入预算必须为正数，重试次数须为 0–5。")
        missing = []
        if not self.settings.base_url:
            missing.append("LLM_BASE_URL")
        if not self.settings.api_key:
            missing.append("LLM_API_KEY")
        if not self.settings.model:
            missing.append("LLM_MODEL")

        if missing:
            joined = ", ".join(missing)
            raise LLMConfigError(f"Missing required LLM setting(s): {joined}")

        parsed_url = urlparse(self.settings.base_url)
        if parsed_url.port == 8501:
            raise LLMConfigError(
                "LLM_BASE_URL 当前指向的是 Streamlit 页面地址。"
                "请填写 OneAI / OneAPI 提供的 OpenAI-compatible API Base URL，"
                "例如：https://your-oneai-domain.example.com/v1"
            )

    @staticmethod
    def _stringify_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "\n".join(part for part in parts if part).strip()
        return str(content)
