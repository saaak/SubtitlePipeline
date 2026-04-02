from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .pipeline import CancellationRequested, PipelineError, TaskContext, extract_audio, process_text_segments, render_srt, run_asr, translate_segments, write_stage_artifacts
from .store import Database, normalize_path


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".m4v"}


@dataclass
class ScanResult:
    scanned: int
    queued: int
    skipped: int


class ScannerService:
    def __init__(self, database: Database):
        self.database = database

    def scan_once(self) -> ScanResult:
        config = self.database.get_config()
        file_config = config["file"]
        input_dir = Path(file_config["input_dir"])
        input_dir.mkdir(parents=True, exist_ok=True)
        allowed = {extension.lower() for extension in file_config.get("allowed_extensions", [])} or VIDEO_EXTENSIONS
        min_size_bytes = int(file_config["min_size_mb"]) * 1024 * 1024
        max_size_bytes = int(file_config["max_size_mb"]) * 1024 * 1024
        scanned = 0
        queued = 0
        skipped = 0
        for path in input_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in allowed:
                continue
            scanned += 1
            stat = path.stat()
            observed = self.database.observe_file(str(path), int(stat.st_size), float(stat.st_mtime))
            if observed["size_bytes"] < min_size_bytes or observed["size_bytes"] > max_size_bytes:
                skipped += 1
                continue
            if observed["stable_hits"] < 2:
                skipped += 1
                continue
            if self.database.has_task_for_file_version(
                observed["path_key"],
                observed["size_bytes"],
                observed["mtime"],
            ):
                skipped += 1
                continue
            if self.database.has_active_task(observed["path_key"]):
                skipped += 1
                continue
            self.database.create_task(
                observed["file_id"],
                observed["path"],
                observed["size_bytes"],
                observed["mtime"],
            )
            queued += 1
        return ScanResult(scanned=scanned, queued=queued, skipped=skipped)

    def run_forever(self) -> None:
        while True:
            self.scan_once()
            interval = int(self.database.get_config()["file"]["scan_interval_seconds"])
            time.sleep(max(interval, 1))


class WorkerService:
    def __init__(self, database: Database):
        self.database = database

    def run_forever(self) -> None:
        while True:
            processed = self.process_next_task()
            if not processed:
                interval = int(self.database.get_config()["processing"]["poll_interval_seconds"])
                time.sleep(max(interval, 1))

    def process_next_task(self) -> bool:
        task = self.database.claim_next_pending_task()
        if not task:
            return False
        try:
            result_payload = self._process_claimed_task(task)
            self.database.mark_task_done(task["id"], result_payload)
        except CancellationRequested:
            self.database.mark_task_cancelled(task["id"], task["stage"])
        except Exception as exc:
            self.database.mark_task_failure(task["id"], task["stage"], str(exc))
        return True

    def _process_claimed_task(self, task: dict[str, Any]) -> dict[str, Any]:
        snapshot = task["config_snapshot"]
        if snapshot is None:
            raise PipelineError("缺少配置快照")
        work_dir = Path(snapshot["processing"]["work_dir"]) / str(task["id"])
        work_dir.mkdir(parents=True, exist_ok=True)
        context = TaskContext(
            task_id=task["id"],
            file_path=task["file_path"],
            config_snapshot=snapshot,
            work_dir=work_dir,
        )
        audio_path = self._run_stage(task["id"], "extract_audio", 10, lambda: extract_audio(context))
        asr_result = self._run_stage(task["id"], "asr", 35, lambda: run_asr(context, audio_path))
        processed_segments = self._run_stage(
            task["id"],
            "text_process",
            55,
            lambda: process_text_segments(asr_result["segments"]),
        )
        translations = self._run_stage(
            task["id"],
            "translate",
            80,
            lambda: translate_segments(context, processed_segments),
        )
        subtitle_paths = self._run_stage(
            task["id"],
            "subtitle_render",
            95,
            lambda: render_srt(context, processed_segments, translations),
        )
        result_payload = {
            "audio_path": str(audio_path),
            "subtitle_paths": subtitle_paths,
            "device": snapshot["whisper"]["device"],
            "translations": list(translations.keys()),
            "file_path_key": normalize_path(task["file_path"]),
        }
        self._run_stage(task["id"], "output_finalize", 100, lambda: write_stage_artifacts(context, result_payload))
        return result_payload

    def _run_stage(self, task_id: int, stage: str, progress: float, action):
        self._ensure_not_cancelled(task_id, stage)
        self.database.update_task_stage(task_id, stage, progress)
        self.database.log(task_id, stage, "INFO", f"开始阶段 {stage}")
        result = action()
        self.database.log(task_id, stage, "INFO", f"完成阶段 {stage}")
        self._ensure_not_cancelled(task_id, stage)
        return result

    def _ensure_not_cancelled(self, task_id: int, stage: str) -> None:
        if self.database.is_cancel_requested(task_id):
            raise CancellationRequested(stage)
