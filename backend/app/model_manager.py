from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DOWNLOAD_STALL_TIMEOUT_SECONDS = 120
DOWNLOAD_PROGRESS_POLL_SECONDS = 3
DEFAULT_PROVIDER = "whisperx"
PROVIDER_ORDER = ("whisperx", "faster-whisper", "anime-whisper", "qwen")
PROVIDER_CONFIG_KEYS = {
    "whisperx": "whisperx",
    "faster-whisper": "faster_whisper",
    "anime-whisper": "anime_whisper",
    "qwen": "qwen",
}
LEGACY_MODEL_ALIASES = {
    "tiny": "whisperx-tiny",
    "small": "whisperx-small",
    "medium": "whisperx-medium",
    "large-v2": "whisperx-large-v2",
    "anime-whisper-medium": "anime-whisper",
}


@dataclass(frozen=True)
class ModelSpec:
    name: str
    repo_id: str
    size_label: str
    estimated_size_bytes: int
    provider: str
    display_name: str
    description: str
    tags: tuple[str, ...]


@dataclass
class DownloadState:
    status: str
    error: str | None = None
    stalled: bool = False
    manual_download_url: str | None = None
    last_progress_at: float = 0
    last_size_bytes: int = 0
    token: int = 0


PROVIDER_INFO: dict[str, dict[str, Any]] = {
    "whisperx": {
        "display_name": "WhisperX",
        "description": "Whisper + CTranslate2 + 强制对齐，时间戳最准确。",
        "features": ["word-level timestamps", "forced alignment", "balanced"],
        "best_for": "需要精确时间戳和稳定字幕切分的场景",
    },
    "faster-whisper": {
        "display_name": "Faster-Whisper",
        "description": "纯 CTranslate2 推理，更轻量、更快，适合快速预览。",
        "features": ["fast inference", "low memory", "vad"],
        "best_for": "快速预览、低延迟批处理和资源受限环境",
    },
    "anime-whisper": {
        "display_name": "Anime-Whisper",
        "description": "面向动漫对白优化的日语语音识别模型。",
        "features": ["anime", "ja optimized", "dialogue"],
        "best_for": "日语动画、Galgame 和高情绪对白",
    },
    "qwen": {
        "display_name": "Qwen-ASR",
        "description": "Qwen3-ASR 系列支持多语言识别、语言检测与时间戳预测。",
        "features": ["multilingual", "language id", "timestamps"],
        "best_for": "多语言混合内容、长音频和需要更强语言覆盖的场景",
    },
}

KNOWN_MODELS = (
    ModelSpec(
        "whisperx-tiny",
        "Systran/faster-whisper-tiny",
        "151 MB",
        151 * 1024 * 1024,
        "whisperx",
        "Tiny",
        "极致轻量，适合低资源设备。",
        ("fast", "lightweight"),
    ),
    ModelSpec(
        "whisperx-small",
        "Systran/faster-whisper-small",
        "488 MB",
        488 * 1024 * 1024,
        "whisperx",
        "Small",
        "速度与质量平衡，适合作为默认模型。",
        ("balanced",),
    ),
    ModelSpec(
        "whisperx-medium",
        "Systran/faster-whisper-medium",
        "1.53 GB",
        1530 * 1024 * 1024,
        "whisperx",
        "Medium",
        "更高识别质量，适合正式转录任务。",
        ("accurate", "balanced"),
    ),
    ModelSpec(
        "whisperx-large-v2",
        "Systran/faster-whisper-large-v2",
        "2.91 GB",
        2910 * 1024 * 1024,
        "whisperx",
        "Large V2",
        "精度优先，适合复杂发音和噪声环境。",
        ("accurate", "large"),
    ),
    ModelSpec(
        "faster-whisper-small",
        "Systran/faster-whisper-small",
        "488 MB",
        488 * 1024 * 1024,
        "faster-whisper",
        "Small",
        "轻量快速，适合快速粗转录。",
        ("fast", "preview"),
    ),
    ModelSpec(
        "faster-whisper-large-v3",
        "Systran/faster-whisper-large-v3",
        "3.09 GB",
        3090 * 1024 * 1024,
        "faster-whisper",
        "Large V3",
        "新版高精度 Faster-Whisper 模型。",
        ("accurate", "fast"),
    ),
    ModelSpec(
        "anime-whisper",
        "litagin/anime-whisper",
        "3.0 GB",
        3072 * 1024 * 1024,
        "anime-whisper",
        "Anime Whisper",
        "针对日语动漫对白和拟声表现优化。",
        ("anime", "ja"),
    ),
    ModelSpec(
        "qwen3-asr-0.6b",
        "Qwen/Qwen3-ASR-0.6B",
        "1.5 GB",
        1536 * 1024 * 1024,
        "qwen",
        "Qwen3 ASR 0.6B",
        "轻量版 Qwen3-ASR，兼顾吞吐与多语言覆盖。",
        ("multilingual", "fast", "language-id"),
    ),
    ModelSpec(
        "qwen3-asr-1.7b",
        "Qwen/Qwen3-ASR-1.7B",
        "3.8 GB",
        3891 * 1024 * 1024,
        "qwen",
        "Qwen3 ASR 1.7B",
        "高精度 Qwen3-ASR，支持更强的复杂场景识别。",
        ("multilingual", "accurate", "timestamps"),
    ),
)
KNOWN_MODELS_BY_NAME = {spec.name: spec for spec in KNOWN_MODELS}


def normalize_provider_name(provider: str | None) -> str:
    value = str(provider or DEFAULT_PROVIDER).strip().lower().replace("_", "-")
    if value == "fasterwhisper":
        return "faster-whisper"
    if value == "animewhisper":
        return "anime-whisper"
    return value or DEFAULT_PROVIDER


def get_provider_config_key(provider: str | None) -> str:
    return PROVIDER_CONFIG_KEYS.get(normalize_provider_name(provider), "whisperx")


def get_default_model_name(provider: str | None = None) -> str:
    normalized_provider = normalize_provider_name(provider)
    for spec in KNOWN_MODELS:
        if spec.provider == normalized_provider:
            return spec.name
    return "whisperx-small"


def resolve_model_name(name: str, provider: str | None = None) -> str:
    candidate = str(name or "").strip()
    if not candidate:
        return get_default_model_name(provider)
    lowered = candidate.lower()
    if lowered in KNOWN_MODELS_BY_NAME:
        return lowered
    if lowered in LEGACY_MODEL_ALIASES:
        return LEGACY_MODEL_ALIASES[lowered]
    normalized_provider = normalize_provider_name(provider)
    prefixed = f"{normalized_provider}-{lowered}"
    if prefixed in KNOWN_MODELS_BY_NAME:
        return prefixed
    return lowered


def infer_provider_from_model_name(name: str, fallback: str | None = None) -> str:
    resolved = resolve_model_name(name, fallback)
    spec = KNOWN_MODELS_BY_NAME.get(resolved)
    if spec is not None:
        return spec.provider
    normalized_fallback = normalize_provider_name(fallback)
    if normalized_fallback in PROVIDER_INFO:
        return normalized_fallback
    if resolved.startswith("faster-whisper-"):
        return "faster-whisper"
    if resolved.startswith("anime-whisper-"):
        return "anime-whisper"
    if resolved.startswith("qwen"):
        return "qwen"
    return DEFAULT_PROVIDER


class ModelManager:
    def __init__(self, models_root: str = "/models", stall_timeout_seconds: int = DOWNLOAD_STALL_TIMEOUT_SECONDS):
        self.models_root = Path(models_root)
        self.models_root.mkdir(parents=True, exist_ok=True)
        self._states: dict[str, DownloadState] = {}
        self._lock = threading.RLock()
        self.stall_timeout_seconds = max(int(stall_timeout_seconds), 1)

    def get_spec(self, name: str, provider: str | None = None) -> ModelSpec:
        canonical_name = resolve_model_name(name, provider)
        spec = KNOWN_MODELS_BY_NAME.get(canonical_name)
        if spec is None:
            raise KeyError(f"unknown model: {name}")
        return spec

    def list_models(self, current_model: str) -> list[dict[str, Any]]:
        current_model_name = resolve_model_name(current_model)
        with self._lock:
            states = dict(self._states)
        items: list[dict[str, Any]] = []
        for spec in KNOWN_MODELS:
            model_dir = self.models_root / spec.name
            state = states.get(spec.name)
            installed = self._is_installed(model_dir)
            if state and state.status == "downloading":
                progress = self._calculate_progress(model_dir, spec.estimated_size_bytes)
                status = "downloading"
            elif installed:
                progress = 100
                status = "installed"
            else:
                progress = 0
                status = "not_installed"
            items.append(
                {
                    "name": spec.name,
                    "repo_id": spec.repo_id,
                    "size_label": spec.size_label,
                    "estimated_size_bytes": spec.estimated_size_bytes,
                    "status": status,
                    "progress": progress,
                    "current": spec.name == current_model_name,
                    "path": str(model_dir),
                    "provider": spec.provider,
                    "display_name": spec.display_name,
                    "description": spec.description,
                    "tags": list(spec.tags),
                    "error": state.error if state and state.error else None,
                    "stalled": bool(state and state.stalled),
                    "manual_download_url": state.manual_download_url if state else self._manual_download_url(spec),
                }
            )
        return items

    def has_model(self, name: str, provider: str | None = None) -> bool:
        spec = self.get_spec(name, provider)
        return self._is_installed(self.models_root / spec.name)

    def has_any_model(self) -> bool:
        return any(self.has_model(spec.name) for spec in KNOWN_MODELS)

    def start_download(self, name: str) -> None:
        spec = self.get_spec(name)
        model_dir = self.models_root / spec.name
        now = time.time()
        with self._lock:
            state = self._states.get(spec.name)
            if state and state.status == "downloading":
                raise ValueError(f"模型 {spec.name} 正在下载中")
            if self._is_installed(model_dir):
                raise ValueError(f"模型 {spec.name} 已安装")
            token = int(now * 1000)
            self._states[spec.name] = DownloadState(
                status="downloading",
                stalled=False,
                manual_download_url=self._manual_download_url(spec),
                last_progress_at=now,
                last_size_bytes=self._directory_size(model_dir),
                token=token,
            )
        model_dir.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._download_model, args=(spec, token), daemon=True).start()
        threading.Thread(target=self._watch_download, args=(spec, token), daemon=True).start()

    def delete_model(self, name: str, current_model: str) -> None:
        spec = self.get_spec(name)
        current_spec = self.get_spec(current_model) if current_model else None
        if current_spec and spec.name == current_spec.name:
            raise ValueError("不能删除当前正在使用的模型")
        with self._lock:
            state = self._states.get(spec.name)
            if state and state.status == "downloading":
                raise ValueError("模型下载中，暂不支持删除")
        model_dir = self.models_root / spec.name
        if model_dir.exists():
            shutil.rmtree(model_dir)
        with self._lock:
            self._states.pop(spec.name, None)

    def _download_model(self, spec: ModelSpec, token: int) -> None:
        model_dir = self.models_root / spec.name
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(repo_id=spec.repo_id, local_dir=str(model_dir))
        except Exception as exc:
            shutil.rmtree(model_dir, ignore_errors=True)
            with self._lock:
                state = self._states.get(spec.name)
                if not state or state.token != token:
                    return
                self._states[spec.name] = DownloadState(
                    status="not_installed",
                    error=self._build_manual_download_message(spec, str(exc)),
                    stalled=False,
                    manual_download_url=self._manual_download_url(spec),
                    token=token,
                )
            return
        with self._lock:
            state = self._states.get(spec.name)
            if not state or state.token != token:
                return
            self._states[spec.name] = DownloadState(
                status="installed",
                stalled=False,
                manual_download_url=self._manual_download_url(spec),
                token=token,
            )

    def _watch_download(self, spec: ModelSpec, token: int) -> None:
        model_dir = self.models_root / spec.name
        while True:
            time.sleep(DOWNLOAD_PROGRESS_POLL_SECONDS)
            current_size = self._directory_size(model_dir)
            now = time.time()
            with self._lock:
                state = self._states.get(spec.name)
                if not state or state.token != token or state.status != "downloading":
                    return
                if current_size > state.last_size_bytes:
                    self._states[spec.name] = DownloadState(
                        status="downloading",
                        stalled=False,
                        manual_download_url=state.manual_download_url,
                        last_progress_at=now,
                        last_size_bytes=current_size,
                        token=token,
                    )
                    continue
                if now - state.last_progress_at >= self.stall_timeout_seconds and not state.stalled:
                    self._states[spec.name] = DownloadState(
                        status="downloading",
                        error=self._build_manual_download_message(spec, f"下载超过 {self.stall_timeout_seconds} 秒没有进度"),
                        stalled=True,
                        manual_download_url=state.manual_download_url,
                        last_progress_at=state.last_progress_at,
                        last_size_bytes=current_size,
                        token=token,
                    )

    def _calculate_progress(self, model_dir: Path, estimated_size_bytes: int) -> int:
        if estimated_size_bytes <= 0 or not model_dir.exists():
            return 0
        current_size = sum(path.stat().st_size for path in model_dir.rglob("*") if path.is_file())
        if current_size <= 0:
            return 0
        ratio = min(current_size / estimated_size_bytes, 0.99)
        return int(ratio * 100)

    def _is_installed(self, model_dir: Path) -> bool:
        if not model_dir.exists() or not model_dir.is_dir():
            return False
        return any(model_dir.iterdir())

    def _directory_size(self, model_dir: Path) -> int:
        if not model_dir.exists():
            return 0
        return sum(path.stat().st_size for path in model_dir.rglob("*") if path.is_file())

    def _manual_download_url(self, spec: ModelSpec) -> str:
        return f"https://huggingface.co/{spec.repo_id}"

    def _build_manual_download_message(self, spec: ModelSpec, reason: str) -> str:
        return f"{reason}。可前往 {self._manual_download_url(spec)} 手动下载后挂载到 /models/{spec.name}"
