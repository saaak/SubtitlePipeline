from __future__ import annotations

from typing import Any

from ..model_manager import DEFAULT_PROVIDER, infer_provider_from_model_name
from .base import ASRProvider
from .cache import WhisperModelCache
from .providers import AnimeWhisperProvider, FasterWhisperProvider, QwenASRProvider, WhisperXProvider


class ASRProviderFactory:
    @staticmethod
    def create(config: dict[str, Any], model_cache: WhisperModelCache | None = None) -> ASRProvider:
        model_name = str(config.get("model_name", ""))
        provider = infer_provider_from_model_name(model_name, DEFAULT_PROVIDER)

        if provider == "whisperx":
            return WhisperXProvider(config, model_cache)
        if provider == "faster-whisper":
            return FasterWhisperProvider(config)
        if provider == "anime-whisper":
            return AnimeWhisperProvider(config)
        if provider == "qwen":
            return QwenASRProvider(config)
        raise ValueError(f"不支持的 ASR Provider: {provider}")
