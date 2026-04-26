from __future__ import annotations

import logging
from typing import Any

from .exceptions import PipelineError
from .helpers import get_models_root

logger = logging.getLogger(__name__)

_WHISPERX_COMPUTE_TYPE_ALIASES = {
    "fp16": "float16",
    "half": "float16",
    "float16": "float16",
    "bf16": "bfloat16",
    "bfloat16": "bfloat16",
    "fp32": "float32",
    "float32": "float32",
    "int8": "int8",
    "int8_float32": "int8_float32",
    "int8-float32": "int8_float32",
    "int8_fp32": "int8_float32",
    "int8-fp32": "int8_float32",
    "int8_float16": "int8_float16",
    "int8-float16": "int8_float16",
    "int8_fp16": "int8_float16",
    "int8-fp16": "int8_float16",
    "int8_bfloat16": "int8_bfloat16",
    "int8-bfloat16": "int8_bfloat16",
    "int8_bf16": "int8_bfloat16",
    "int8-bf16": "int8_bfloat16",
    "int16": "int16",
    "auto": "auto",
    "default": "default",
}


def _resolve_whisperx_compute_type(value: Any) -> str | None:
    requested = str(value or "auto").strip().lower()
    if not requested or requested == "auto":
        return None
    compute_type = _WHISPERX_COMPUTE_TYPE_ALIASES.get(requested)
    if compute_type is None:
        raise PipelineError(
            "whisperx compute_type 不支持: "
            f"{value!r}，可用 auto/default/float32/float16/bfloat16/int8/int8_float16/int8_float32/int8_bfloat16/int16"
        )
    return compute_type


class WhisperModelCache:
    def __init__(self) -> None:
        self._model: Any | None = None
        self._model_name: str | None = None
        self._model_device: str | None = None
        self._model_language: str | None = None
        self._model_compute_type: str | None = None
        self._align_model: Any | None = None
        self._align_metadata: Any | None = None
        self._align_language: str | None = None
        self._align_device: str | None = None

    def get_model(self, name: str, device: str, language: str | None = None, compute_type: Any = "auto") -> Any:
        resolved_compute_type = _resolve_whisperx_compute_type(compute_type)
        if (
            self._model is not None
            and self._model_name == name
            and self._model_device == device
            and self._model_language == language
            and self._model_compute_type == resolved_compute_type
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
        if resolved_compute_type is not None:
            kwargs["compute_type"] = resolved_compute_type
        logger.info(
            "加载 WhisperX 模型: %s, device=%s, compute_type=%s",
            model_reference,
            device,
            resolved_compute_type or "auto",
        )
        self._model = whisperx.load_model(model_reference, device, **kwargs)
        self._model_name = name
        self._model_device = device
        self._model_language = language
        self._model_compute_type = resolved_compute_type
        logger.info("WhisperX 模型加载完成: %s", model_reference)
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
