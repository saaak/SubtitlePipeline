from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .pipeline import (
    CancellationRequested,
    PipelineError,
    TaskContext,
    build_result_payload,
    cleanup_intermediates,
    cleanup_work_dir_intermediates,
    ensure_intermediates_dir,
    extract_audio,
    load_asr_result,
    load_processed_segments,
    read_stage_artifacts,
    load_translations,
    mux_subtitle,
    process_text_segments,
    render_srt,
    resolve_audio_path,
    run_asr,
    save_asr_result,
    save_processed_segments,
    save_translations,
    translate_segments,
    write_stage_artifacts,
    WhisperModelCache,
)
from .store import Database


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".m4v"}
logger = logging.getLogger(__name__)


def _mux_output_suffix(config: dict) -> str:
    """Return the fixed suffix of mux output filenames (e.g. '.subbed.mkv')."""
    template = str(config.get("mux", {}).get("filename_template", "")).strip()
    if not template:
        return ""
    suffix = template.replace("{stem}", "")
    return suffix if suffix else ""


def _is_inside_directory(path: Path, directory: Path) -> bool:
    try:
        return path.resolve().is_relative_to(directory.resolve())
    except OSError:
        return False


def _should_skip_scan_path(path: Path, config: dict[str, Any]) -> bool:
    if ".subpipeline" in path.parts:
        return True
    if not bool(config.get("file", {}).get("output_to_source_dir", True)):
        output_dir = Path(os.environ.get("SUBPIPELINE_OUTPUT_DIR", "/output"))
        if _is_inside_directory(path, output_dir):
            return True
    mux_suffix = _mux_output_suffix(config)
    return bool(mux_suffix and path.name.endswith(mux_suffix))


@dataclass
class ScanResult:
    scanned: int
    queued: int
    skipped: int
    pending_count: int
    remaining_slots: int
    throttled: bool


class ScannerService:
    def __init__(self, database: Database):
        self.database = database

    def scan_once(self) -> ScanResult:
        config = self.database.get_config()
        file_config = config["file"]
        scanner_config = config.get("scanner", {})
        input_dir = Path(file_config["input_dir"])
        input_dir.mkdir(parents=True, exist_ok=True)
        allowed = {extension.lower() for extension in file_config.get("allowed_extensions", [])} or VIDEO_EXTENSIONS
        min_size_bytes = int(file_config["min_size_mb"]) * 1024 * 1024
        max_size_bytes = int(file_config["max_size_mb"]) * 1024 * 1024
        max_pending_tasks = max(int(scanner_config.get("max_pending_tasks", 5)), 0)
        pending_count = self.database.count_tasks_by_status("pending")
        remaining_slots = max(max_pending_tasks - pending_count, 0)
        scanned = 0
        queued = 0
        skipped = 0
        if remaining_slots <= 0:
            return ScanResult(
                scanned=scanned,
                queued=queued,
                skipped=skipped,
                pending_count=pending_count,
                remaining_slots=remaining_slots,
                throttled=True,
            )
        # 收集所有文件，按文件夹创建时间（新→旧）和路径深度（外→内）排序
        all_files = [p for p in input_dir.rglob("*") if p.is_file()]

        @lru_cache(maxsize=None)
        def _dir_ctime(d: str) -> float:
            try:
                return os.stat(d).st_ctime
            except OSError:
                return 0.0

        input_depth = len(input_dir.parts)

        def _sort_key(p: Path):
            depth = len(p.parts) - input_depth - 1          # 外层优先 (小 → 大)
            parent_ctime = _dir_ctime(str(p.parent))        # 新建优先 (大 → 小)
            return (depth, -parent_ctime, p.name)

        all_files.sort(key=_sort_key)

        for path in all_files:
            if _should_skip_scan_path(path, config):
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
            remaining_slots -= 1
            if remaining_slots <= 0:
                break
        return ScanResult(
            scanned=scanned,
            queued=queued,
            skipped=skipped,
            pending_count=pending_count,
            remaining_slots=remaining_slots,
            throttled=queued == 0 and pending_count >= max_pending_tasks,
        )

    def run_forever(self) -> None:
        while True:
            result = self.scan_once()
            logger.info(
                "扫描完成 scanned=%d queued=%d skipped=%d pending=%d slots=%d throttled=%s",
                result.scanned,
                result.queued,
                result.skipped,
                result.pending_count,
                result.remaining_slots,
                result.throttled,
            )
            interval = int(self.database.get_config()["file"]["scan_interval_seconds"])
            time.sleep(max(interval, 1))


class WorkerService:
    def __init__(self, database: Database):
        self.database = database
        self.model_cache = WhisperModelCache()

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
            latest = self.database.get_task(task["id"])
            self.database.mark_task_cancelled(task["id"], latest["stage"] if latest else task["stage"])
        except Exception as exc:
            latest = self.database.get_task(task["id"])
            self.database.mark_task_failure(task["id"], latest["stage"] if latest else task["stage"], str(exc))
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
        intermediates_dir = ensure_intermediates_dir(context)
        if context.using_fallback_intermediates:
            self.database.log(
                task["id"],
                task["stage"],
                "WARNING",
                "源文件目录不可写，已回退到工作目录保存中间产物",
                {"intermediates_dir": str(intermediates_dir)},
            )
        start_stage = str(task["stage"])
        audio_path: Path | None = None
        asr_result: dict[str, Any] | None = None
        processed_segments: list[dict[str, Any]] | None = None
        translations: dict[str, list[str]] | None = None
        subtitle_paths: list[str] | None = None
        result_payload: dict[str, Any] | None = None
        if start_stage not in {"queued", "extract_audio"}:
            audio_path = resolve_audio_path(context)
        if start_stage in {"text_process", "translate", "subtitle_render", "output_finalize", "mux"}:
            asr_result = load_asr_result(context)
        if start_stage in {"translate", "subtitle_render", "output_finalize", "mux"}:
            processed_segments = load_processed_segments(context)
        if snapshot["translation"]["enabled"] and start_stage in {"subtitle_render", "output_finalize", "mux"}:
            translations = load_translations(context)
        if start_stage in {"output_finalize", "mux"}:
            if processed_segments is None:
                raise PipelineError("缺少字幕渲染依赖，无法继续执行")
            subtitle_paths = render_srt(context, processed_segments, translations or {})
        if start_stage == "mux":
            result_payload = read_stage_artifacts(context)
        if start_stage in {"queued", "extract_audio"}:
            audio_path = self._run_stage(task["id"], "extract_audio", 10, lambda: extract_audio(context))
        if start_stage in {"queued", "extract_audio", "asr"}:
            if audio_path is None:
                raise PipelineError("缺少音频文件，无法执行 ASR")
            asr_result = self._run_stage(task["id"], "asr", 35, lambda: run_asr(context, audio_path, self.model_cache))
            save_asr_result(context, asr_result)
        if start_stage in {"queued", "extract_audio", "asr", "text_process"}:
            if asr_result is None:
                raise PipelineError("缺少 ASR 结果，无法继续执行")
            processed_segments = self._run_stage(
                task["id"],
                "text_process",
                55,
                lambda: process_text_segments(asr_result["segments"]),
            )
            save_processed_segments(context, processed_segments)
        if start_stage in {"queued", "extract_audio", "asr", "text_process", "translate"}:
            if processed_segments is None:
                raise PipelineError("缺少分段结果，无法继续执行")
            translations = self._run_stage(
                task["id"],
                "translate",
                60,
                lambda: translate_segments(
                    context,
                    processed_segments,
                    progress_callback=lambda current, total: self.database.update_task_stage(
                        task["id"],
                        "translate",
                        60 + int(20 * current / total),
                    ),
                ),
            )
            save_translations(context, translations)
        if start_stage in {"queued", "extract_audio", "asr", "text_process", "translate", "subtitle_render"}:
            if processed_segments is None:
                raise PipelineError("缺少字幕渲染输入，无法继续执行")
            subtitle_paths = self._run_stage(
                task["id"],
                "subtitle_render",
                95,
                lambda: render_srt(context, processed_segments, translations or {}),
            )
        if audio_path is None or subtitle_paths is None:
            raise PipelineError("缺少最终输出所需产物")
        if start_stage in {"queued", "extract_audio", "asr", "text_process", "translate", "subtitle_render", "output_finalize"}:
            result_payload = build_result_payload(context, audio_path, subtitle_paths, translations or {})
            self._run_stage(task["id"], "output_finalize", 100, lambda: write_stage_artifacts(context, result_payload))
        if result_payload is None:
            raise PipelineError("缺少任务结果元数据")
        if snapshot["mux"]["enabled"]:
            mux_path = self._run_stage(task["id"], "mux", 100, lambda: mux_subtitle(context, subtitle_paths))
            result_payload["mux_path"] = mux_path
            write_stage_artifacts(context, result_payload)
        if not snapshot["processing"]["keep_intermediates"]:
            cleanup_intermediates(Path(task["file_path"]))
            if context.using_fallback_intermediates:
                cleanup_work_dir_intermediates(context.work_dir)
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
