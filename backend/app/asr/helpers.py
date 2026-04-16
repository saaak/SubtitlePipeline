from __future__ import annotations

import os
import wave
from pathlib import Path
from typing import Any

from ..model_manager import KNOWN_MODELS_BY_NAME


def get_models_root() -> Path:
    return Path(os.environ.get("SUBPIPELINE_MODELS_DIR", "/models"))


def resolve_provider_model_reference(model_name: str, provider: str) -> str:
    models_root = get_models_root()
    local_model_dir = models_root / model_name
    if local_model_dir.exists():
        return str(local_model_dir)
    if provider in {"whisperx", "faster-whisper"} and "-" in model_name:
        return model_name.split("-", 1)[1]
    spec = KNOWN_MODELS_BY_NAME.get(model_name)
    return spec.repo_id if spec is not None else model_name


def normalize_asr_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for segment in segments:
        normalized.append(
            {
                "start": float(segment.get("start", 0.0)),
                "end": float(segment.get("end", segment.get("start", 0.0))),
                "text": str(segment.get("text", "")).strip(),
            }
        )
    return normalized


def estimate_audio_duration(audio_path: Path) -> float:
    try:
        if audio_path.suffix.lower() == ".wav":
            with wave.open(str(audio_path), "rb") as wav_file:
                frame_rate = wav_file.getframerate()
                if frame_rate > 0:
                    return wav_file.getnframes() / float(frame_rate)
    except Exception:
        pass
    try:
        import librosa  # type: ignore

        return float(librosa.get_duration(path=str(audio_path)))
    except Exception:
        return 0.0
