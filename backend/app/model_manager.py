from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DOWNLOAD_STALL_TIMEOUT_SECONDS = 120
DOWNLOAD_PROGRESS_POLL_SECONDS = 3


@dataclass(frozen=True)
class ModelSpec:
    name: str
    repo_id: str
    size_label: str
    estimated_size_bytes: int


@dataclass
class DownloadState:
    status: str
    error: str | None = None
    stalled: bool = False
    manual_download_url: str | None = None
    last_progress_at: float = 0
    last_size_bytes: int = 0
    token: int = 0


KNOWN_MODELS = (
    ModelSpec("tiny", "Systran/faster-whisper-tiny", "151 MB", 151 * 1024 * 1024),
    ModelSpec("small", "Systran/faster-whisper-small", "488 MB", 488 * 1024 * 1024),
    ModelSpec("medium", "Systran/faster-whisper-medium", "1.53 GB", 1530 * 1024 * 1024),
    ModelSpec("large-v2", "Systran/faster-whisper-large-v2", "2.91 GB", 2910 * 1024 * 1024),
)


class ModelManager:
    def __init__(self, models_root: str = "/models", stall_timeout_seconds: int = DOWNLOAD_STALL_TIMEOUT_SECONDS):
        self.models_root = Path(models_root)
        self.models_root.mkdir(parents=True, exist_ok=True)
        self._states: dict[str, DownloadState] = {}
        self._lock = threading.RLock()
        self.stall_timeout_seconds = max(int(stall_timeout_seconds), 1)

    def get_spec(self, name: str) -> ModelSpec:
        for spec in KNOWN_MODELS:
            if spec.name == name:
                return spec
        raise KeyError(f"unknown model: {name}")

    def list_models(self, current_model: str) -> list[dict[str, Any]]:
        with self._lock:
            states = dict(self._states)
        items: list[dict[str, Any]] = []
        for spec in KNOWN_MODELS:
            model_dir = self.models_root / spec.name
            state = states.get(spec.name)
            installed = self._is_installed(model_dir)
            progress = None
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
                    "current": spec.name == current_model,
                    "path": str(model_dir),
                    "error": state.error if state and state.error else None,
                    "stalled": bool(state and state.stalled),
                    "manual_download_url": state.manual_download_url if state else self._manual_download_url(spec),
                }
            )
        return items

    def has_model(self, name: str) -> bool:
        self.get_spec(name)
        return self._is_installed(self.models_root / name)

    def has_any_model(self) -> bool:
        return any(self.has_model(spec.name) for spec in KNOWN_MODELS)

    def start_download(self, name: str) -> None:
        spec = self.get_spec(name)
        model_dir = self.models_root / name
        now = time.time()
        with self._lock:
            state = self._states.get(name)
            if state and state.status == "downloading":
                raise ValueError(f"模型 {name} 正在下载中")
            if self._is_installed(model_dir):
                raise ValueError(f"模型 {name} 已安装")
            token = int(now * 1000)
            self._states[name] = DownloadState(
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
        self.get_spec(name)
        if name == current_model:
            raise ValueError("不能删除当前正在使用的模型")
        with self._lock:
            state = self._states.get(name)
            if state and state.status == "downloading":
                raise ValueError("模型下载中，暂不支持删除")
        model_dir = self.models_root / name
        if model_dir.exists():
            shutil.rmtree(model_dir)
        with self._lock:
            self._states.pop(name, None)

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
