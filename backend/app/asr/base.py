from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..model_manager import get_default_model_name, normalize_provider_name, resolve_model_name


class ASRProvider(ABC):
    def __init__(self, config: dict[str, Any], provider_name: str) -> None:
        self.config = config
        self.provider_name = normalize_provider_name(provider_name)
        self.device = str(config.get("device", "cpu"))
        self.model_name = resolve_model_name(
            str(config.get("model_name", get_default_model_name(self.provider_name))),
            self.provider_name,
        )
        self.beam_size = int(config.get("beam_size", 5))
        self.vad_filter = bool(config.get("vad_filter", True))
        self.vad_threshold = float(config.get("vad_threshold", 0.5))
        self.align_method = str(config.get("align_method", "auto"))
        advanced = config.get("advanced", {})
        self.advanced = advanced if isinstance(advanced, dict) else {}

    @abstractmethod
    def transcribe(self, audio_path: Path, language: str | None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def supports_model(self, model_name: str) -> bool:
        raise NotImplementedError
