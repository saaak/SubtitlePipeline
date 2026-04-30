from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

import openai
from openai import OpenAI


SUPPORTED_LLM_TYPES = {
    "openai-chat": {
        "label": "OpenAI Chat Completions",
        "default_base_url": "https://api.openai.com",
        "requires_api_key": True,
    },
    "openai-responses": {
        "label": "OpenAI Responses",
        "default_base_url": "https://api.openai.com",
        "requires_api_key": True,
    },
    "openai-compatible": {
        "label": "OpenAI Compatible",
        "default_base_url": "https://api.openai.com",
        "requires_api_key": True,
    },
    "anthropic": {
        "label": "Anthropic Messages",
        "default_base_url": "https://api.anthropic.com",
        "requires_api_key": True,
    },
    "lmstudio": {
        "label": "LM Studio",
        "default_base_url": "http://localhost:1234",
        "requires_api_key": False,
    },
    "ollama": {
        "label": "Ollama",
        "default_base_url": "http://localhost:11434",
        "requires_api_key": False,
    },
}


class LLMError(RuntimeError):
    pass


class LLMRateLimitError(LLMError):
    pass


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


class LLMClient:
    def complete(self, messages: list[LLMMessage]) -> str:
        raise NotImplementedError

    def resolved_base_url(self) -> str:
        raise NotImplementedError


def normalize_llm_type(value: str | None) -> str:
    normalized = str(value or "openai-compatible").strip().lower()
    legacy_mapping = {
        "openai": "openai-chat",
        "openai-chat": "openai-chat",
        "openai_chat": "openai-chat",
        "chat": "openai-chat",
        "chat-completions": "openai-chat",
        "chat_completions": "openai-chat",
        "openai-responses": "openai-responses",
        "openai_responses": "openai-responses",
        "responses": "openai-responses",
        "openai_compatible": "openai-compatible",
        "openai-compatible": "openai-compatible",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "lmstudio": "lmstudio",
        "lm-studio": "lmstudio",
        "lm_studio": "lmstudio",
        "ollama": "ollama",
    }
    return legacy_mapping.get(normalized, "openai-compatible")


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


class OpenAICompatibleLLMClient(LLMClient):
    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        *,
        default_base_url: str | None = None,
        requires_api_key: bool = True,
    ):
        self.api_base_url = (api_base_url or default_base_url or SUPPORTED_LLM_TYPES["openai-compatible"]["default_base_url"]).rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.requires_api_key = requires_api_key
        self.client = OpenAI(
            api_key=self.api_key or "missing-api-key",
            base_url=self.resolved_base_url(),
            timeout=float(self.timeout_seconds),
            max_retries=0,
        )

    def resolved_base_url(self) -> str:
        if self.api_base_url.endswith("/v1"):
            return self.api_base_url
        return f"{self.api_base_url}/v1"

    def complete(self, messages: list[LLMMessage]) -> str:
        if self.requires_api_key and not self.api_key:
            raise LLMError("translation.api_key 未配置，无法调用 OpenAI-compatible 翻译服务")
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": item.role, "content": item.content} for item in messages],
                max_tokens=8192,
                stream=True,
                temperature=0.3,
                frequency_penalty=1.2,
                presence_penalty=0.8,
            )
            parts: list[str] = []
            finish_reason: str | None = None
            for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                if choice.delta and choice.delta.content:
                    parts.append(choice.delta.content)
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
        except openai.AuthenticationError as exc:
            raise LLMError("翻译服务鉴权失败，请检查 API Key") from exc
        except openai.RateLimitError as exc:
            raise LLMRateLimitError("翻译服务触发限流，请稍后重试") from exc
        except openai.BadRequestError as exc:
            raise LLMError(f"翻译请求参数无效: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise LLMError("翻译服务连接失败，请检查 API 地址、网络或服务状态") from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"翻译服务返回异常状态: {exc.status_code}") from exc
        except openai.APIError as exc:
            raise LLMError(f"翻译服务调用失败: {exc}") from exc
        content = "".join(parts)
        if not content:
            raise LLMError("翻译服务未返回文本内容")
        if finish_reason == "length":
            # The caller can still try to parse partial output and retry missing lines.
            pass
        return content


class OpenAIResponsesLLMClient(LLMClient):
    def __init__(self, api_base_url: str, api_key: str, model: str, timeout_seconds: int):
        self.api_base_url = (api_base_url or SUPPORTED_LLM_TYPES["openai-responses"]["default_base_url"]).rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.client = OpenAI(
            api_key=self.api_key or "missing-api-key",
            base_url=self.resolved_base_url(),
            timeout=float(self.timeout_seconds),
            max_retries=0,
        )

    def resolved_base_url(self) -> str:
        if self.api_base_url.endswith("/v1"):
            return self.api_base_url
        return f"{self.api_base_url}/v1"

    def complete(self, messages: list[LLMMessage]) -> str:
        if not self.api_key:
            raise LLMError("translation.api_key 未配置，无法调用 OpenAI Responses 翻译服务")
        instructions = "\n\n".join(item.content for item in messages if item.role == "system")
        input_text = "\n\n".join(item.content for item in messages if item.role != "system")
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=instructions or None,
                input=input_text,
                max_output_tokens=8192,
                temperature=0.3,
            )
        except openai.AuthenticationError as exc:
            raise LLMError("翻译服务鉴权失败，请检查 API Key") from exc
        except openai.RateLimitError as exc:
            raise LLMRateLimitError("翻译服务触发限流，请稍后重试") from exc
        except openai.BadRequestError as exc:
            raise LLMError(f"翻译请求参数无效: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise LLMError("翻译服务连接失败，请检查 API 地址、网络或服务状态") from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"翻译服务返回异常状态: {exc.status_code}") from exc
        except openai.APIError as exc:
            raise LLMError(f"翻译服务调用失败: {exc}") from exc
        content = str(getattr(response, "output_text", "") or "").strip()
        if not content:
            content = self._extract_output_text(response).strip()
        if not content:
            raise LLMError("OpenAI Responses 翻译服务未返回文本内容")
        return content

    def _extract_output_text(self, response: Any) -> str:
        parts: list[str] = []
        output = getattr(response, "output", None)
        if output is None and isinstance(response, dict):
            output = response.get("output")
        if not isinstance(output, list):
            return ""
        for item in output:
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                text = getattr(part, "text", None)
                if text is None and isinstance(part, dict):
                    text = part.get("text")
                if text:
                    parts.append(str(text))
        return "".join(parts)


class JsonHttpLLMClient(LLMClient):
    def __init__(self, api_base_url: str, api_key: str, model: str, timeout_seconds: int):
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                **headers,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429:
                raise LLMRateLimitError("翻译服务触发限流，请稍后重试") from exc
            raise LLMError(f"翻译服务返回异常状态: {exc.code} {message[:300]}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"翻译服务连接失败: {exc.reason}") from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"翻译服务返回了无法解析的 JSON: {raw[:300]}") from exc
        if not isinstance(parsed, dict):
            raise LLMError("翻译服务返回内容格式无效")
        return parsed


class AnthropicLLMClient(JsonHttpLLMClient):
    def __init__(self, api_base_url: str, api_key: str, model: str, timeout_seconds: int):
        super().__init__(api_base_url or SUPPORTED_LLM_TYPES["anthropic"]["default_base_url"], api_key, model, timeout_seconds)

    def resolved_base_url(self) -> str:
        return self.api_base_url

    def _messages_url(self) -> str:
        if self.api_base_url.endswith("/v1"):
            return _join_url(self.api_base_url, "/messages")
        return _join_url(self.api_base_url, "/v1/messages")

    def complete(self, messages: list[LLMMessage]) -> str:
        if not self.api_key:
            raise LLMError("translation.api_key 未配置，无法调用 Anthropic 翻译服务")
        system_prompt = "\n\n".join(item.content for item in messages if item.role == "system")
        user_messages = [
            {"role": "assistant" if item.role == "assistant" else "user", "content": item.content}
            for item in messages
            if item.role != "system"
        ]
        if system_prompt:
            if user_messages:
                user_messages[0]["content"] = f"{system_prompt}\n\n{user_messages[0]['content']}"
            else:
                user_messages.append({"role": "user", "content": system_prompt})
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 8192,
            "temperature": 0.3,
            "messages": user_messages,
        }
        response = self._post_json(
            self._messages_url(),
            payload,
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        parts = response.get("content")
        if not isinstance(parts, list):
            raise LLMError("Anthropic 翻译服务返回内容格式无效")
        text = "".join(str(item.get("text", "")) for item in parts if isinstance(item, dict) and item.get("type") == "text")
        if not text:
            raise LLMError("Anthropic 翻译服务未返回文本内容")
        return text


class OllamaLLMClient(JsonHttpLLMClient):
    def __init__(self, api_base_url: str, api_key: str, model: str, timeout_seconds: int):
        super().__init__(api_base_url or SUPPORTED_LLM_TYPES["ollama"]["default_base_url"], api_key, model, timeout_seconds)

    def resolved_base_url(self) -> str:
        return self.api_base_url

    def _chat_url(self) -> str:
        if self.api_base_url.endswith("/api"):
            return _join_url(self.api_base_url, "/chat")
        return _join_url(self.api_base_url, "/api/chat")

    def complete(self, messages: list[LLMMessage]) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "options": {
                "temperature": 0.3,
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = self._post_json(self._chat_url(), payload, headers)
        message = response.get("message")
        if not isinstance(message, dict):
            raise LLMError("Ollama 翻译服务返回内容格式无效")
        content = str(message.get("content", "")).strip()
        if not content:
            raise LLMError("Ollama 翻译服务未返回文本内容")
        return content


def create_llm_client(
    llm_type: str | None,
    api_base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: int,
) -> LLMClient:
    normalized = normalize_llm_type(llm_type)
    if normalized == "openai-chat":
        return OpenAICompatibleLLMClient(
            api_base_url,
            api_key,
            model,
            timeout_seconds,
            default_base_url=SUPPORTED_LLM_TYPES["openai-chat"]["default_base_url"],
            requires_api_key=True,
        )
    if normalized == "openai-responses":
        return OpenAIResponsesLLMClient(api_base_url, api_key, model, timeout_seconds)
    if normalized == "anthropic":
        return AnthropicLLMClient(api_base_url, api_key, model, timeout_seconds)
    if normalized == "lmstudio":
        return OpenAICompatibleLLMClient(
            api_base_url,
            api_key,
            model,
            timeout_seconds,
            default_base_url=SUPPORTED_LLM_TYPES["lmstudio"]["default_base_url"],
            requires_api_key=False,
        )
    if normalized == "ollama":
        return OllamaLLMClient(api_base_url, api_key, model, timeout_seconds)
    return OpenAICompatibleLLMClient(api_base_url, api_key, model, timeout_seconds)
