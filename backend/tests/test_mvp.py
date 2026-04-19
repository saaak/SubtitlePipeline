from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.asr import ASRProviderFactory, FasterWhisperProvider, WhisperModelCache, WhisperXProvider, run_asr
from app.main import create_app
from app.model_manager import DownloadState, ModelManager, infer_provider_from_model_name, resolve_model_name
from app.pipeline import (
    FORMAT_INSTRUCTION,
    TRANSLATION_PRESETS,
    PipelineError,
    TaskContext,
    build_chunk_user_message,
    build_chunks,
    debug_translation_request,
    extract_audio,
    mux_subtitle,
    parse_chunk_output,
    parse_numbered_lines,
    translate_segments,
)
from app.runtime import ScannerService, WorkerService
from app.store import Database


class SubtitlePipelineMvpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.data_dir = self.base / "data"
        self.output_dir = self.base / "output"
        self.config_dir = self.base / "config"
        self.models_dir = self.base / "models"
        self.frontend_dist = self.base / "frontend-dist"
        for path in (self.data_dir, self.output_dir, self.config_dir, self.models_dir, self.frontend_dist):
            path.mkdir(parents=True, exist_ok=True)
        (self.frontend_dist / "index.html").write_text("<!doctype html><title>SubPipeline</title>", encoding="utf-8")

        self.database = Database(str(self.config_dir / "api.db"))
        self.database.initialize()
        self.database.update_config(
            {
                "file": {
                    "input_dir": str(self.data_dir),
                    "output_to_source_dir": False,
                    "min_size_mb": 0,
                    "allowed_extensions": [".mp4"],
                },
                "processing": {
                    "work_dir": str(self.config_dir / "work"),
                    "max_retries": 1,
                },
                "translation": {
                    "enabled": False,
                    "target_languages": ["zh-CN"],
                    "max_retries": 1,
                    "api_base_url": "https://api.openai.com",
                    "api_key": "",
                    "model": "gpt-4o-mini",
                },
                "subtitle": {
                    "bilingual": True,
                    "bilingual_mode": "merge",
                    "filename_template": "{stem}.{lang}.srt",
                },
            }
        )

        self.previous_env = {
            "SUBPIPELINE_DB_PATH": os.environ.get("SUBPIPELINE_DB_PATH"),
            "SUBPIPELINE_FRONTEND_DIST": os.environ.get("SUBPIPELINE_FRONTEND_DIST"),
            "SUBPIPELINE_MODELS_DIR": os.environ.get("SUBPIPELINE_MODELS_DIR"),
            "SUBPIPELINE_BROWSE_ROOTS": os.environ.get("SUBPIPELINE_BROWSE_ROOTS"),
            "SUBPIPELINE_OUTPUT_DIR": os.environ.get("SUBPIPELINE_OUTPUT_DIR"),
            "HTTP_PROXY": os.environ.get("HTTP_PROXY"),
            "HTTPS_PROXY": os.environ.get("HTTPS_PROXY"),
            "HF_ENDPOINT": os.environ.get("HF_ENDPOINT"),
        }
        os.environ["SUBPIPELINE_DB_PATH"] = str(self.config_dir / "api.db")
        os.environ["SUBPIPELINE_FRONTEND_DIST"] = str(self.frontend_dist)
        os.environ["SUBPIPELINE_MODELS_DIR"] = str(self.models_dir)
        os.environ["SUBPIPELINE_BROWSE_ROOTS"] = ",".join([str(self.data_dir), str(self.output_dir), str(self.config_dir)])
        os.environ["SUBPIPELINE_OUTPUT_DIR"] = str(self.output_dir)

    def tearDown(self) -> None:
        for key, value in self.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp_dir.cleanup()

    def _create_installed_model(self, name: str) -> None:
        model_dir = self.models_dir / resolve_model_name(name)
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "weights.bin").write_bytes(b"model")

    def _fake_whisperx(self) -> types.SimpleNamespace:
        class FakeModel:
            def transcribe(self, audio_path: str):
                return {
                    "language": "en",
                    "segments": [
                        {"start": 0.0, "end": 1.2, "text": "hello world"},
                        {"start": 1.2, "end": 2.4, "text": "second line"},
                    ],
                }

        return types.SimpleNamespace(
            load_model=lambda *args, **kwargs: FakeModel(),
            load_align_model=lambda **kwargs: ("align-model", {"meta": True}),
            align=lambda segments, align_model, metadata, audio_path, device: {"segments": segments},
        )

    def _stream_chunks(self, content: str):
        return [
            types.SimpleNamespace(
                choices=[
                    types.SimpleNamespace(
                        delta=types.SimpleNamespace(content=content),
                        finish_reason="stop",
                    )
                ]
            )
        ]

    def test_database_filters_obsolete_fields_and_tracks_setup_status(self) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO system_config (group_name, key_name, value_json, scope, restart_required, updated_at)
                VALUES ('translation', 'provider', '"mock"', 'system', 0, 'now')
                """
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO system_config (group_name, key_name, value_json, scope, restart_required, updated_at)
                VALUES ('scanner', 'max_pending_tasks', '5', 'runtime', 0, 'now')
                """
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO system_config (group_name, key_name, value_json, scope, restart_required, updated_at)
                VALUES ('file', 'output_dir', '"/legacy-output"', 'runtime', 0, 'now')
                """
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO system_config (group_name, key_name, value_json, scope, restart_required, updated_at)
                VALUES ('mux', 'output_dir', '""', 'runtime', 0, 'now')
                """
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO system_config (group_name, key_name, value_json, scope, restart_required, updated_at)
                VALUES ('subtitle', 'text_process_style', '"basic"', 'runtime', 0, 'now')
                """
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO system_config (group_name, key_name, value_json, scope, restart_required, updated_at)
                VALUES ('whisper', 'align_model', '"auto"', 'system', 0, 'now')
                """
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO system_config (group_name, key_name, value_json, scope, restart_required, updated_at)
                VALUES ('logging', 'page_size', '50', 'runtime', 0, 'now')
                """
            )
        self.database.initialize()
        config = self.database.get_config()
        self.assertNotIn("provider", config["translation"])
        self.assertNotIn("backend_mode", config["processing"])
        self.assertNotIn("scanner", config)
        self.assertNotIn("in_place", config["file"])
        self.assertNotIn("output_dir", config["file"])
        self.assertTrue("output_to_source_dir" in config["file"])
        self.assertFalse(config["file"]["output_to_source_dir"])
        self.assertNotIn("text_process_style", config["subtitle"])
        self.assertNotIn("align_model", config["whisper"])
        self.assertNotIn("output_dir", config["mux"])
        self.assertNotIn("page_size", config["logging"])
        self.assertEqual(config["processing"]["retry_mode"], "restart")
        self.assertFalse(config["processing"]["keep_intermediates"])
        self.assertIn("mux", config)

        status = self.database.get_system_status()
        self.assertFalse(status["setup_complete"])
        self.assertTrue(status["translation_ready"])

        updated = self.database.set_setup_complete(True)
        self.assertTrue(updated["setup_complete"])

    def test_scanner_waits_until_setup_complete(self) -> None:
        scanner = ScannerService(self.database)
        with patch.object(self.database, "is_setup_complete", return_value=False), \
             patch.object(scanner, "scan_once") as mock_scan_once, \
             patch("app.runtime.time.sleep", side_effect=RuntimeError("stop")) as mock_sleep:
            with self.assertRaisesRegex(RuntimeError, "stop"):
                scanner.run_forever()
        mock_scan_once.assert_not_called()
        mock_sleep.assert_called_once_with(5)

    @patch("app.model_manager.DOWNLOAD_PROGRESS_POLL_SECONDS", 0.1)
    def test_model_download_stall_exposes_manual_download_hint(self) -> None:
        manager = ModelManager(str(self.models_dir), stall_timeout_seconds=1)
        fake_hub = types.SimpleNamespace(snapshot_download=lambda **kwargs: time.sleep(2))
        with patch.dict(sys.modules, {"huggingface_hub": fake_hub}, clear=False):
            manager.start_download("whisperx-tiny")
            time.sleep(1.2)

        item = next(model for model in manager.list_models(current_model="whisperx-small") if model["name"] == "whisperx-tiny")
        self.assertEqual(item["status"], "downloading")
        self.assertTrue(item["stalled"])
        self.assertIn("huggingface.co/Systran/faster-whisper-tiny", item["manual_download_url"])
        self.assertIn("/models/whisperx-tiny", item["error"])

    @patch("app.pipeline.OpenAI")
    def test_api_endpoints_cover_system_status_translation_and_models(self, mock_openai: MagicMock) -> None:
        self._create_installed_model("whisperx-small")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._stream_chunks("0|测试成功")
        mock_openai.return_value = mock_client

        app = create_app()
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/health").status_code, 200)

            config_response = client.get("/api/config")
            self.assertEqual(config_response.status_code, 200)
            self.assertNotIn("provider", config_response.json()["translation"])
            self.assertIn("mux", config_response.json())

            status_response = client.get("/api/system/status")
            self.assertEqual(status_response.status_code, 200)
            self.assertFalse(status_response.json()["setup_complete"])
            self.assertTrue(status_response.json()["asr_ready"])
            self.assertEqual(status_response.json()["current_provider"], "whisperx")

            translation_response = client.post(
                "/api/translation/test",
                json={
                    "enabled": True,
                    "api_base_url": "https://api.openai.com",
                    "api_key": "test-key",
                    "model": "gpt-4o-mini",
                    "target_language": "zh-CN",
                },
            )
            self.assertEqual(translation_response.status_code, 200)
            self.assertTrue(translation_response.json()["success"])

            setup_response = client.post("/api/system/setup-complete", json={"setup_complete": True})
            self.assertEqual(setup_response.status_code, 200)
            self.assertTrue(setup_response.json()["setup_complete"])

            models_response = client.get("/api/models")
            self.assertEqual(models_response.status_code, 200)
            self.assertEqual(models_response.json()["items"][1]["name"], "whisperx-small")
            self.assertEqual(models_response.json()["items"][1]["status"], "installed")
            self.assertIn("providers", models_response.json())
            self.assertEqual(models_response.json()["items"][1]["provider"], "whisperx")
            self.assertEqual(models_response.json()["items"][1]["model_type"], "asr")

            activate_response = client.post("/api/models/whisperx-small/activate")
            self.assertEqual(activate_response.status_code, 200)
            self.assertEqual(activate_response.json()["config"]["whisper"]["model_name"], "whisperx-small")
            self.assertEqual(activate_response.json()["config"]["whisper"]["provider"], "whisperx")

            browse_response = client.get("/api/browse", params={"path": str(self.data_dir)})
            self.assertEqual(browse_response.status_code, 200)
            self.assertEqual(browse_response.json()["current"], str(self.data_dir.resolve()))

    def test_system_status_api_returns_proxy_config(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "http://proxy.local:7890",
                "HTTPS_PROXY": "http://secure-proxy.local:7890",
                "HF_ENDPOINT": "https://hf-mirror.com",
            },
            clear=False,
        ):
            app = create_app()
            with TestClient(app) as client:
                response = client.get("/api/system/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["proxy"],
            {
                "http_proxy": "http://proxy.local:7890",
                "https_proxy": "http://secure-proxy.local:7890",
                "hf_endpoint": "https://hf-mirror.com",
            },
        )

    def test_api_tasks_includes_status_counts(self) -> None:
        statuses = ["pending", "processing", "failed", "done", "cancelled"]
        for index, status in enumerate(statuses, start=1):
            video_path = self.data_dir / f"task-{index}.mp4"
            video_path.write_bytes(f"video-{index}".encode())
            observed = self.database.observe_file(str(video_path), int(video_path.stat().st_size), float(video_path.stat().st_mtime))
            task = self.database.create_task(observed["file_id"], observed["path"], observed["size_bytes"], observed["mtime"])
            with self.database.connect() as connection:
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = ?, stage = ?, updated_at = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (status, status, f"now-{index}", f"now-{index}" if status in {"failed", "done", "cancelled"} else None, task["id"]),
                )

        app = create_app()
        with TestClient(app) as client:
            response = client.get("/api/tasks")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status_counts"]["pending"], 1)
            self.assertEqual(payload["status_counts"]["processing"], 1)
            self.assertEqual(payload["status_counts"]["failed"], 1)
            self.assertEqual(payload["status_counts"]["done"], 1)
            self.assertEqual(payload["status_counts"]["cancelled"], 1)

    def test_resume_retry_modes_and_resume_check(self) -> None:
        video_path = self.data_dir / "resume_demo.mp4"
        video_path.write_bytes(b"demo-video-content")
        observed = self.database.observe_file(str(video_path), int(video_path.stat().st_size), float(video_path.stat().st_mtime))
        task = self.database.create_task(observed["file_id"], observed["path"], observed["size_bytes"], observed["mtime"])
        snapshot = self.database.get_config()
        snapshot["translation"]["enabled"] = False
        snapshot_json = json.dumps(
            {
                group_name: group_values
                for group_name, group_values in snapshot.items()
                if group_name in {"file", "processing", "whisper", "translation", "subtitle", "mux"}
            }
        )
        intermediates_dir = video_path.parent / ".subpipeline" / video_path.stem
        intermediates_dir.mkdir(parents=True, exist_ok=True)
        (intermediates_dir / "audio.wav").write_bytes(b"audio")
        (intermediates_dir / "asr_result.json").write_text(json.dumps({"segments": [{"start": 0, "end": 1, "text": "hello"}]}), encoding="utf-8")
        (intermediates_dir / "processed_segments.json").write_text(
            json.dumps([{"start": 0, "end": 1, "text": "hello."}]),
            encoding="utf-8",
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = 'failed', stage = 'translate', progress = 80, config_snapshot = ?, updated_at = ?
                WHERE id = ?
                """,
                (snapshot_json, "now", task["id"]),
            )

        app = create_app()
        with TestClient(app) as client:
            resume_check = client.get(f"/api/tasks/{task['id']}/resume-check")
            self.assertEqual(resume_check.status_code, 200)
            self.assertTrue(resume_check.json()["can_resume"])
            self.assertEqual(resume_check.json()["resume_stage"], "align_segments")

            resume_retry = client.post(f"/api/tasks/{task['id']}/retry", json={"mode": "resume"})
            self.assertEqual(resume_retry.status_code, 200)
            resumed = self.database.get_task(task["id"])
            self.assertIsNotNone(resumed)
            assert resumed is not None
            self.assertEqual(resumed["status"], "pending")
            self.assertEqual(resumed["stage"], "align_segments")

            (intermediates_dir / "aligned_segments.json").write_text(
                json.dumps([{"start": 0, "end": 1, "text": "hello"}]),
                encoding="utf-8",
            )

            with self.database.connect() as connection:
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed', stage = 'translate', progress = 80, updated_at = ?
                    WHERE id = ?
                    """,
                    ("later", task["id"]),
                )

            restart_retry = client.post(f"/api/tasks/{task['id']}/retry", json={"mode": "restart"})
            self.assertEqual(restart_retry.status_code, 200)
            restarted = self.database.get_task(task["id"])
            self.assertIsNotNone(restarted)
            assert restarted is not None
            self.assertEqual(restarted["stage"], "queued")
            self.assertFalse(intermediates_dir.exists())

    def test_config_migrates_align_method_to_align_provider(self) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO system_config (group_name, key_name, value_json, scope, restart_required, updated_at)
                VALUES ('whisper', 'align_method', '"whisperx"', 'runtime', 0, 'now')
                """
            )
            connection.execute("DELETE FROM system_config WHERE group_name = 'whisper' AND key_name = 'align_provider'")
        self.database.initialize()
        config = self.database.get_config()
        self.assertEqual(config["whisper"]["align_provider"], "auto")
        self.assertNotIn("align_method", config["whisper"])

    def test_explicit_align_provider_persists(self) -> None:
        self.database.update_config({"whisper": {"align_provider": "whisperx"}})
        config = self.database.get_config()
        self.assertEqual(config["whisper"]["align_provider"], "whisperx")

    def test_model_progress_shows_nonzero_when_files_exist(self) -> None:
        manager = ModelManager(str(self.models_dir))
        model_dir = self.models_dir / "qwen3-forced-aligner"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "part.bin").write_bytes(b"x" * 1024)
        with manager._lock:
            manager._states["qwen3-forced-aligner"] = DownloadState(
                status="downloading",
                manual_download_url="https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B",
            )
        item = next(model for model in manager.list_models(current_model="whisperx-small") if model["name"] == "qwen3-forced-aligner")
        self.assertEqual(item["status"], "downloading")
        self.assertGreaterEqual(item["progress"], 1)

    def test_resume_check_prefers_translate_when_align_checkpoint_exists(self) -> None:
        video_path = self.data_dir / "resume_with_align.mp4"
        video_path.write_bytes(b"demo-video-content")
        observed = self.database.observe_file(str(video_path), int(video_path.stat().st_size), float(video_path.stat().st_mtime))
        task = self.database.create_task(observed["file_id"], observed["path"], observed["size_bytes"], observed["mtime"])
        snapshot = self.database.get_config()
        snapshot["translation"]["enabled"] = False
        snapshot_json = json.dumps(
            {
                group_name: group_values
                for group_name, group_values in snapshot.items()
                if group_name in {"file", "processing", "whisper", "translation", "subtitle", "mux"}
            }
        )
        intermediates_dir = video_path.parent / ".subpipeline" / video_path.stem
        intermediates_dir.mkdir(parents=True, exist_ok=True)
        (intermediates_dir / "audio.wav").write_bytes(b"audio")
        (intermediates_dir / "asr_result.json").write_text(json.dumps({"segments": [{"start": 0, "end": 1, "text": "hello"}]}), encoding="utf-8")
        (intermediates_dir / "aligned_segments.json").write_text(json.dumps([{"start": 0, "end": 1, "text": "hello"}]), encoding="utf-8")
        (intermediates_dir / "processed_segments.json").write_text(json.dumps([{"start": 0, "end": 1, "text": "hello."}]), encoding="utf-8")
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = 'failed', stage = 'translate', progress = 80, config_snapshot = ?, updated_at = ?
                WHERE id = ?
                """,
                (snapshot_json, "now", task["id"]),
            )

        feasibility = self.database.get_task(task["id"])
        self.assertIsNotNone(feasibility)
        assert feasibility is not None
        resume_check = self.database.request_retry(task["id"], mode="resume")
        self.assertIsNotNone(resume_check)
        updated = self.database.get_task(task["id"])
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["stage"], "translate")

    @patch("app.pipeline.OpenAI")
    def test_worker_failure_keeps_failed_stage_and_logs_newest_first(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("translation down")
        mock_openai.return_value = mock_client
        self.database.update_config(
            {
                "translation": {
                    "enabled": True,
                    "target_languages": ["zh-CN"],
                    "max_retries": 1,
                    "api_base_url": "https://api.openai.com",
                    "api_key": "test-key",
                    "model": "gpt-4o-mini",
                },
                "processing": {
                    "max_retries": 0,
                },
            }
        )
        self._create_installed_model("whisperx-small")
        video_path = self.data_dir / "translate_fail.mp4"
        video_path.write_bytes(b"demo-video-content")
        scanner = ScannerService(self.database)
        scanner.scan_once()
        scanner.scan_once()

        with patch.dict(sys.modules, {"whisperx": self._fake_whisperx()}, clear=False):
            with patch("app.pipeline.shutil.which", return_value="ffmpeg"), patch("app.pipeline.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                worker = WorkerService(self.database)
                self.assertTrue(worker.process_next_task())

        task = self.database.list_tasks(page=1, page_size=10).items[0]
        failed_task = self.database.get_task(task["id"])
        self.assertIsNotNone(failed_task)
        assert failed_task is not None
        self.assertEqual(failed_task["status"], "failed")
        self.assertEqual(failed_task["stage"], "translate")

        logs = self.database.get_logs(task["id"], page=1, page_size=20).items
        self.assertGreaterEqual(len(logs), 2)
        self.assertEqual(logs[0]["stage"], "translate")
        self.assertIn("translation down", logs[0]["message"])
        self.assertGreaterEqual(logs[0]["timestamp"], logs[1]["timestamp"])

    def test_scan_stability_and_end_to_end_output(self) -> None:
        self._create_installed_model("whisperx-small")
        video_path = self.data_dir / "demo_video.mp4"
        video_path.write_bytes(b"demo-video-content")
        scanner = ScannerService(self.database)
        self.assertEqual(scanner.scan_once().queued, 0)
        self.assertEqual(scanner.scan_once().queued, 1)
        with patch.dict(sys.modules, {"whisperx": self._fake_whisperx()}, clear=False):
            with patch("app.pipeline.shutil.which", return_value="ffmpeg"), patch("app.pipeline.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                worker = WorkerService(self.database)
                self.assertTrue(worker.process_next_task())

        task = self.database.get_task(self.database.list_tasks(page=1, page_size=10).items[0]["id"])
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task["status"], "done")
        subtitle_path = Path(task["result_payload"]["subtitle_paths"][0])
        self.assertTrue(subtitle_path.exists())
        self.assertEqual(subtitle_path.parent, self.output_dir)
        self.assertIn("hello world.", subtitle_path.read_text(encoding="utf-8"))

    def test_output_to_source_dir_writes_subtitle_next_to_source_video(self) -> None:
        self._create_installed_model("whisperx-small")
        self.database.update_config({"file": {"output_to_source_dir": True}})
        video_path = self.data_dir / "source_output.mp4"
        video_path.write_bytes(b"demo-video-content")
        scanner = ScannerService(self.database)
        scanner.scan_once()
        scanner.scan_once()

        with patch.dict(sys.modules, {"whisperx": self._fake_whisperx()}, clear=False):
            with patch("app.pipeline.shutil.which", return_value="ffmpeg"), patch("app.pipeline.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                worker = WorkerService(self.database)
                self.assertTrue(worker.process_next_task())

        task = self.database.get_task(self.database.list_tasks(page=1, page_size=10).items[0]["id"])
        self.assertIsNotNone(task)
        assert task is not None
        subtitle_path = Path(task["result_payload"]["subtitle_paths"][0])
        self.assertEqual(subtitle_path.parent, video_path.parent)

    def test_scanner_skips_fixed_output_directory_files(self) -> None:
        self.database.update_config({"file": {"input_dir": str(self.base), "output_to_source_dir": False}})
        source_video = self.data_dir / "scan_me.mp4"
        source_video.write_bytes(b"source-video")
        generated_output = self.output_dir / "scan_me.subbed.mkv"
        generated_output.write_bytes(b"mux-output")
        scanner = ScannerService(self.database)

        self.assertEqual(scanner.scan_once().queued, 0)
        result = scanner.scan_once()

        self.assertEqual(result.queued, 1)
        tasks = self.database.list_tasks(page=1, page_size=10).items
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["file_path"], str(source_video))

    def test_processed_file_version_is_not_requeued_without_changes(self) -> None:
        video_path = self.data_dir / "stable_once.mp4"
        video_path.write_bytes(b"demo-video-content")
        scanner = ScannerService(self.database)
        scanner.scan_once()
        self.assertEqual(scanner.scan_once().queued, 1)
        task = self.database.list_tasks(page=1, page_size=10).items
        self.assertEqual(len(task), 1)

        third_scan = scanner.scan_once()
        self.assertEqual(third_scan.queued, 0)
        self.assertEqual(len(self.database.list_tasks(page=1, page_size=10).items), 1)

    def test_changed_file_version_is_requeued(self) -> None:
        video_path = self.data_dir / "updated.mp4"
        video_path.write_bytes(b"version-one")
        scanner = ScannerService(self.database)
        scanner.scan_once()
        scanner.scan_once()
        first_task = self.database.list_tasks(page=1, page_size=10).items[0]
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = 'done', stage = 'output_finalize', progress = 100, updated_at = ?, finished_at = ?
                WHERE id = ?
                """,
                ("done", "done", first_task["id"]),
            )

        video_path.write_bytes(b"version-two-with-different-size")
        stat = video_path.stat()
        os.utime(video_path, (stat.st_atime, stat.st_mtime + 2))
        scanner.scan_once()
        next_scan = scanner.scan_once()
        self.assertEqual(next_scan.queued, 1)
        self.assertEqual(len(self.database.list_tasks(page=1, page_size=10).items), 2)

    @patch("app.pipeline.OpenAI")
    def test_failed_translation_requeues_then_fails(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("translation down")
        mock_openai.return_value = mock_client
        self.database.update_config(
            {
                "translation": {
                    "enabled": True,
                    "target_languages": ["zh-CN"],
                    "max_retries": 1,
                    "api_base_url": "https://api.openai.com",
                    "api_key": "test-key",
                    "model": "gpt-4o-mini",
                }
            }
        )
        snapshot = self.database.get_config()
        context = TaskContext(
            task_id=1,
            file_path=str(self.data_dir / "provider_demo.mp4"),
            config_snapshot=snapshot,
            work_dir=self.config_dir / "work" / "provider",
        )
        segments = [{"start": 0.0, "end": 1.0, "text": "hello"}]

        with self.assertRaises(RuntimeError):
            translate_segments(context, segments)

    def test_config_snapshot_is_frozen_for_processing_task(self) -> None:
        video_path = self.data_dir / "snapshot_demo.mp4"
        video_path.write_bytes(b"demo-video-content")
        scanner = ScannerService(self.database)
        scanner.scan_once()
        scanner.scan_once()

        task = self.database.claim_next_pending_task()
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task["config_snapshot"]["translation"]["target_languages"], ["zh-CN"])

        self.database.update_config({"translation": {"target_languages": ["fr"]}})
        frozen_task = self.database.get_task(task["id"])
        self.assertIsNotNone(frozen_task)
        assert frozen_task is not None
        self.assertEqual(frozen_task["config_snapshot"]["translation"]["target_languages"], ["zh-CN"])

    def test_persistent_database_reuses_single_connection(self) -> None:
        persistent_database = Database(str(self.config_dir / "persistent.db"), persistent=True)
        persistent_database.initialize()

        with persistent_database.connect() as first_connection:
            first_id = id(first_connection)
            first_connection.execute(
                """
                INSERT INTO system_config (group_name, key_name, value_json, scope, restart_required, updated_at)
                VALUES ('runtime-test', 'value', '"ok"', 'runtime', 0, 'now')
                ON CONFLICT(group_name, key_name)
                DO UPDATE SET value_json = excluded.value_json
                """
            )
        with persistent_database.connect() as second_connection:
            self.assertEqual(first_id, id(second_connection))
            row = second_connection.execute(
                """
                SELECT value_json
                FROM system_config
                WHERE group_name = 'runtime-test' AND key_name = 'value'
                """
            ).fetchone()
        self.assertIsNotNone(persistent_database._conn)
        self.assertEqual(id(persistent_database._conn), first_id)
        self.assertEqual(row["value_json"], '"ok"')
        persistent_database.close()
        self.assertIsNone(persistent_database._conn)

    def test_build_chunks_and_boundaries(self) -> None:
        segments = [{"start": float(index), "end": float(index + 1), "text": f"line {index}"} for index in range(120)]
        chunks = build_chunks(segments, chunk_size=50, context_size=10)

        self.assertEqual(len(chunks), 3)
        self.assertEqual([line.index for line in chunks[0].context_before], [])
        self.assertEqual([line.index for line in chunks[0].main_segments[:2]], [0, 1])
        self.assertEqual([line.index for line in chunks[0].context_after], list(range(50, 60)))
        self.assertEqual([line.index for line in chunks[1].context_before], list(range(40, 50)))
        self.assertEqual([line.index for line in chunks[1].main_segments[:2]], [50, 51])
        self.assertEqual([line.index for line in chunks[1].context_after], list(range(100, 110)))
        self.assertEqual([line.index for line in chunks[2].context_before], list(range(90, 100)))
        self.assertEqual([line.index for line in chunks[2].main_segments[-2:]], [118, 119])
        self.assertEqual([line.index for line in chunks[2].context_after], [])
        self.assertTrue(chunks[0].use_sections)

        single = build_chunks(segments[:20], chunk_size=50, context_size=10)
        self.assertEqual(len(single), 1)
        self.assertFalse(single[0].use_sections)

    def test_build_chunk_user_message(self) -> None:
        segments = [{"start": float(index), "end": float(index + 1), "text": f"line {index}"} for index in range(55)]
        chunk = build_chunks(segments, chunk_size=50, context_size=2)[0]
        message = build_chunk_user_message(chunk)
        self.assertIn("[翻译]", message)
        self.assertIn("[下文]", message)
        self.assertIn("0|line 0", message)
        self.assertIn("50|line 50", message)

        single_chunk = build_chunks(segments[:3], chunk_size=50, context_size=2)[0]
        single_message = build_chunk_user_message(single_chunk)
        self.assertNotIn("[翻译]", single_message)
        self.assertEqual(single_message, "0|line 0\n1|line 1\n2|line 2")

    def test_parse_numbered_lines(self) -> None:
        self.assertEqual(
            parse_numbered_lines("0|你好\n1|世界", [0, 1]),
            ["你好", "世界"],
        )
        self.assertEqual(
            parse_numbered_lines("0|你好\n1|世界\n2|忽略\n3|也忽略\n5|再忽略", [0, 1, 2, 3, 4], ["a", "b", "c", "d", "e"]),
            ["你好", "世界", "忽略", "也忽略", "e"],
        )
        self.assertIsNone(parse_numbered_lines("0|你好", [0, 1, 2], ["a", "b", "c"]))

    def test_parse_chunk_output_fallbacks(self) -> None:
        self.assertEqual(
            parse_chunk_output("0|你好\n1|世界", [0, 1], ["hello", "world"]),
            ["你好", "世界"],
        )
        self.assertEqual(
            parse_chunk_output('["你好", "世界"]', [0, 1], ["hello", "world"], lambda content: json.loads(content)),
            ["你好", "世界"],
        )
        self.assertEqual(
            parse_chunk_output("你好\n世界", [0, 1], ["hello", "world"]),
            ["你好", "世界"],
        )

    def test_ffmpeg_timeout_raises_pipeline_error(self) -> None:
        snapshot = self.database.get_config()
        snapshot["translation"]["enabled"] = False
        context = TaskContext(
            task_id=1,
            file_path=str(self.data_dir / "timeout.mp4"),
            config_snapshot=snapshot,
            work_dir=self.config_dir / "work" / "timeout",
        )
        Path(context.file_path).write_bytes(b"timeout-video")
        subtitle_path = self.output_dir / "timeout.zh-CN.srt"
        subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")

        with patch("app.pipeline.shutil.which", return_value="ffmpeg"), patch(
            "app.pipeline.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=7200),
        ):
            with self.assertRaises(PipelineError) as extract_error:
                extract_audio(context)
            self.assertIn("7200", str(extract_error.exception))

            with self.assertRaises(PipelineError) as mux_error:
                mux_subtitle(context, [str(subtitle_path)])
            self.assertIn("7200", str(mux_error.exception))

    def test_whisper_model_cache_reuses_loaded_models(self) -> None:
        load_model_calls: list[tuple[str, str, str, str | None]] = []
        load_align_calls: list[tuple[str, str]] = []

        class FakeModel:
            pass

        def fake_load_model(name: str, device: str, download_root: str, language: str | None = None):
            load_model_calls.append((name, device, download_root, language))
            return FakeModel()

        def fake_load_align_model(language_code: str, device: str):
            load_align_calls.append((language_code, device))
            return (object(), {"language_code": language_code})

        fake_whisperx = types.SimpleNamespace(
            load_model=fake_load_model,
            load_align_model=fake_load_align_model,
        )

        cache = WhisperModelCache()
        with patch.dict(sys.modules, {"whisperx": fake_whisperx}, clear=False):
            first_model = cache.get_model("whisperx-small", "cpu")
            second_model = cache.get_model("whisperx-small", "cpu")
            third_model = cache.get_model("whisperx-small", "cpu", "ja")
            first_align = cache.get_align_model("en", "cpu")
            second_align = cache.get_align_model("en", "cpu")

        self.assertIs(first_model, second_model)
        self.assertIsNot(first_model, third_model)
        self.assertIs(first_align[0], second_align[0])
        self.assertEqual(len(load_model_calls), 2)
        self.assertEqual(load_model_calls[1][3], "ja")
        self.assertEqual(len(load_align_calls), 1)

    def test_run_asr_passes_source_language_to_whisper_model(self) -> None:
        load_model_calls: list[tuple[str, str, str, str | None]] = []

        class FakeModel:
            def transcribe(self, audio_path: str):
                return {
                    "language": "ja",
                    "segments": [
                        {"start": 0.0, "end": 1.0, "text": "こんにちは"},
                    ],
                }

        fake_whisperx = types.SimpleNamespace(
            load_model=lambda name, device, download_root, language=None: load_model_calls.append((name, device, download_root, language)) or FakeModel(),
            load_align_model=lambda language_code, device: (object(), {"language_code": language_code}),
            align=lambda segments, align_model, metadata, audio_path, device: {"segments": segments},
        )
        snapshot = self.database.get_config()
        snapshot["subtitle"]["source_language"] = "ja"
        audio_path = self.config_dir / "source-language.wav"
        audio_path.write_bytes(b"audio")
        context = TaskContext(
            task_id=1,
            file_path=str(self.data_dir / "source-language.mp4"),
            config_snapshot=snapshot,
            work_dir=self.config_dir / "work" / "source-language",
        )

        with patch.dict(sys.modules, {"whisperx": fake_whisperx}, clear=False):
            result = run_asr(context, audio_path)

        self.assertEqual(result["segments"][0]["text"], "こんにちは")
        self.assertEqual(load_model_calls[0][3], "ja")
        self.assertEqual(result["provider"], "whisperx")

    def test_asr_provider_factory_defaults_to_whisperx(self) -> None:
        provider = ASRProviderFactory.create({"model_name": "small", "device": "cpu"})
        self.assertIsInstance(provider, WhisperXProvider)

    def test_activate_model_updates_provider_by_prefix(self) -> None:
        self._create_installed_model("faster-whisper-small")
        app = create_app()
        with TestClient(app) as client:
            response = client.post("/api/models/faster-whisper-small/activate")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["config"]["whisper"]["provider"], "faster-whisper")
        self.assertEqual(response.json()["config"]["whisper"]["model_name"], "faster-whisper-small")

    def test_infer_provider_from_model_name_supports_legacy_alias(self) -> None:
        self.assertEqual(infer_provider_from_model_name("small"), "whisperx")
        self.assertEqual(resolve_model_name("small"), "whisperx-small")
        self.assertEqual(resolve_model_name("anime-whisper-medium"), "anime-whisper")

    def test_faster_whisper_provider_supports_prefixed_models(self) -> None:
        provider = FasterWhisperProvider(
            {
                "provider": "faster-whisper",
                "model_name": "faster-whisper-small",
                "device": "cpu",
                "provider_config": {"faster_whisper": {}},
            }
        )
        self.assertTrue(provider.supports_model("faster-whisper-large-v3"))

    @patch("app.pipeline.OpenAI")
    def test_build_prompt_supports_presets_and_custom_prompt(self, mock_openai: MagicMock) -> None:
        mock_openai.return_value = MagicMock()
        from app.pipeline import OpenAICompatibleTranslationProvider

        provider = OpenAICompatibleTranslationProvider(
            api_base_url="https://api.openai.com",
            api_key="test-key",
            model="gpt-4o-mini",
            timeout_seconds=30,
        )
        movie_prompt = provider._build_prompt("zh-CN", "movie", "")
        custom_prompt = provider._build_prompt("zh-CN", "movie", "custom style")

        self.assertIn(TRANSLATION_PRESETS["movie"], movie_prompt)
        self.assertIn(FORMAT_INSTRUCTION.format(target_language="zh-CN"), movie_prompt)
        self.assertIn("custom style", custom_prompt)
        self.assertNotIn(TRANSLATION_PRESETS["movie"], custom_prompt)

    @patch("app.pipeline.OpenAI")
    def test_translate_segments_chunked_flow(self, mock_openai: MagicMock) -> None:
        def fake_create(*args, **kwargs):
            user_content = kwargs["messages"][1]["content"]
            translate_section = user_content.split("[翻译]\n", 1)[1] if "[翻译]\n" in user_content else user_content
            translate_section = translate_section.split("\n\n[下文]", 1)[0]
            lines = [line for line in translate_section.splitlines() if line.strip()]
            content = "\n".join(
                f"{prefix}|ZH-{text}"
                for prefix, text in (line.split("|", 1) for line in lines)
            )
            return self._stream_chunks(content)

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = fake_create
        mock_openai.return_value = mock_client

        snapshot = self.database.get_config()
        snapshot["translation"].update(
            {
                "enabled": True,
                "api_key": "test-key",
                "content_type": "movie",
                "custom_prompt": "",
                "target_languages": ["zh-CN"],
                "max_retries": 1,
            }
        )
        context = TaskContext(
            task_id=1,
            file_path=str(self.data_dir / "provider_demo.mp4"),
            config_snapshot=snapshot,
            work_dir=self.config_dir / "work" / "provider",
        )
        segments = [
            {"start": float(index), "end": float(index + 1), "text": f"line {index}"}
            for index in range(60)
        ]
        progress_events: list[tuple[int, int]] = []

        translations = translate_segments(
            context,
            segments,
            progress_callback=lambda current, total: progress_events.append((current, total)),
        )

        self.assertEqual(len(translations["zh-CN"]), 60)
        self.assertEqual(translations["zh-CN"][0], "ZH-line 0")
        self.assertEqual(translations["zh-CN"][-1], "ZH-line 59")
        self.assertEqual(progress_events[-1], (4, 4))
        self.assertEqual(mock_client.chat.completions.create.call_count, 4)

    @patch("app.pipeline.OpenAI")
    def test_openai_compatible_translation_provider(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._stream_chunks('["你好", "世界"]')
        mock_openai.return_value = mock_client

        snapshot = self.database.get_config()
        snapshot["translation"].update(
            {
                "enabled": True,
                "api_base_url": "https://api.openai.com",
                "api_key": "test-key",
                "model": "gpt-4o-mini",
                "target_languages": ["zh-CN"],
            }
        )
        context = TaskContext(
            task_id=1,
            file_path=str(self.data_dir / "provider_demo.mp4"),
            config_snapshot=snapshot,
            work_dir=self.config_dir / "work" / "provider",
        )
        segments = [
            {"start": 0.0, "end": 1.0, "text": "hello"},
            {"start": 1.0, "end": 2.0, "text": "world"},
        ]

        translations = translate_segments(context, segments)
        self.assertEqual(translations["zh-CN"], ["你好", "世界"])
        self.assertEqual(mock_client.chat.completions.create.call_args.kwargs["model"], "gpt-4o-mini")

    @patch("app.pipeline.OpenAI")
    def test_translation_debug_and_fenced_json_response(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._stream_chunks('```json\n["你好，世界。", "第二行。"]\n```')
        mock_openai.return_value = mock_client

        result = debug_translation_request(
            api_base_url="http://example.com:8317",
            api_key="test-key",
            model="deepseek-chat",
            timeout_seconds=30,
            target_language="zh-CN",
            texts=["hello world.", "second line."],
        )

        self.assertEqual(result["parsed"], ["你好，世界。", "第二行。"])
        self.assertEqual(result["base_url"], "http://example.com:8317/v1")


if __name__ == "__main__":
    unittest.main()
