from __future__ import annotations

from typing import Any

from .exceptions import PipelineError
from .helpers import get_models_root


class WhisperModelCache:
    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str | None = None
        self._model_device: str | None = None
        self._model_language: str | None = None
        self._align_model: Any | None = None
        self._align_metadata: Any | None = None
        self._align_language: str | None = None
        self._align_device: str | None = None

    def get_model(self, name: str, device: str, language: str | None = None) -> Any:
        if (
            self._model is not None
            and self._model_name == name
            and self._model_device == device
            and self._model_language == language
        ):
            return self._model
        try:
            import whisperx  # type: ignore
        except ImportError as exc:
            raise PipelineError("whisperx 未安装，无法执行真实识别") from exc
        models_root = get_models_root()
        local_model_dir = models_root / name
        model_reference = str(local_model_dir) if local_model_dir.exists() else name
        kwargs = {"download_root": str(models_root)}
        if language is not None:
            kwargs["language"] = language
        self._model = whisperx.load_model(model_reference, device, **kwargs)
        self._model_name = name
        self._model_device = device
        self._model_language = language
        return self._model

    def get_align_model(self, language: str, device: str) -> tuple[Any, Any]:
        if (
            self._align_model is not None
            and self._align_language == language
            and self._align_device == device
        ):
            return self._align_model, self._align_metadata
        try:
            import whisperx  # type: ignore
        except ImportError as exc:
            raise PipelineError("whisperx 未安装，无法执行真实识别") from exc
        self._align_model, self._align_metadata = whisperx.load_align_model(
            language_code=language,
            device=device,
        )
        self._align_language = language
        self._align_device = device
        return self._align_model, self._align_metadata
