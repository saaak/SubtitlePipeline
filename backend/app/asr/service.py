from __future__ import annotations

from pathlib import Path
from typing import Any

from ..model_manager import (
    DEFAULT_PROVIDER,
    get_default_model_name,
    infer_provider_from_model_name,
    normalize_provider_name,
    resolve_model_name,
)
from .cache import WhisperModelCache
from .factory import ASRProviderFactory
from .helpers import normalize_asr_segments


def run_asr(
    context: Any,
    audio_path: Path,
    model_cache: WhisperModelCache | None = None,
    database: Any = None,
) -> dict[str, Any]:
    whisper_config = context.config_snapshot["whisper"]
    subtitle_config = context.config_snapshot["subtitle"]
    source_language = str(subtitle_config.get("source_language", "auto")).strip().lower()
    language_hint = source_language if source_language and source_language != "auto" else None
    provider_name = normalize_provider_name(
        whisper_config.get("provider")
        or infer_provider_from_model_name(str(whisper_config.get("model_name", "")), DEFAULT_PROVIDER)
    )
    canonical_whisper_config = {
        **whisper_config,
        "provider": provider_name,
        "model_name": resolve_model_name(
            str(whisper_config.get("model_name", get_default_model_name(provider_name))),
            provider_name,
        ),
    }

    model_name = canonical_whisper_config["model_name"]
    device = canonical_whisper_config["device"]
    if database is not None:
        database.log(context.task_id, "asr", "INFO", f"ASR 配置: 模型={model_name}, Provider={provider_name}, 设备={device}")

    provider = ASRProviderFactory.create(canonical_whisper_config, model_cache or WhisperModelCache())
    result = provider.transcribe(audio_path, language_hint)

    if database is not None:
        database.log(
            context.task_id,
            "asr",
            "INFO",
            f"ASR 完成: 识别到 {len(result.get('segments', []))} 个片段, 语言={result.get('language', 'unknown')}",
        )

    return {
        "segments": normalize_asr_segments(result.get("segments", [])),
        "language": str(result.get("language", language_hint or "auto")),
        "device": canonical_whisper_config["device"],
        "audio_path": str(audio_path),
        "provider": provider.provider_name,
    }
