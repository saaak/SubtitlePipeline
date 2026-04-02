from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.main import create_app
from app.pipeline import TaskContext, translate_segments
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

        self.database = Database(str(self.config_dir / "subpipeline.db"))
        self.database.initialize()
        self.database.update_config(
            {
                "file": {
                    "input_dir": str(self.data_dir),
                    "output_dir": str(self.output_dir),
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
        }
        os.environ["SUBPIPELINE_DB_PATH"] = str(self.config_dir / "api.db")
        os.environ["SUBPIPELINE_FRONTEND_DIST"] = str(self.frontend_dist)
        os.environ["SUBPIPELINE_MODELS_DIR"] = str(self.models_dir)

    def tearDown(self) -> None:
        for key, value in self.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp_dir.cleanup()

    def _create_installed_model(self, name: str) -> None:
        model_dir = self.models_dir / name
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

    def test_database_filters_obsolete_fields_and_tracks_setup_status(self) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO system_config (group_name, key_name, value_json, scope, restart_required, updated_at)
                VALUES ('translation', 'provider', '"mock"', 'system', 0, 'now')
                """
            )
        self.database.initialize()
        config = self.database.get_config()
        self.assertNotIn("provider", config["translation"])
        self.assertNotIn("backend_mode", config["processing"])

        status = self.database.get_system_status()
        self.assertFalse(status["setup_complete"])
        self.assertTrue(status["translation_ready"])

        updated = self.database.set_setup_complete(True)
        self.assertTrue(updated["setup_complete"])

    @patch("app.pipeline.httpx.post")
    def test_api_endpoints_cover_system_status_translation_and_models(self, mock_post: MagicMock) -> None:
        self._create_installed_model("small")
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": '["测试成功"]'}}]}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        app = create_app()
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/health").status_code, 200)

            config_response = client.get("/api/config")
            self.assertEqual(config_response.status_code, 200)
            self.assertNotIn("provider", config_response.json()["translation"])

            status_response = client.get("/api/system/status")
            self.assertEqual(status_response.status_code, 200)
            self.assertFalse(status_response.json()["setup_complete"])
            self.assertTrue(status_response.json()["asr_ready"])

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
            self.assertEqual(models_response.json()["items"][1]["name"], "small")
            self.assertEqual(models_response.json()["items"][1]["status"], "installed")

            activate_response = client.post("/api/models/small/activate")
            self.assertEqual(activate_response.status_code, 200)
            self.assertEqual(activate_response.json()["config"]["whisper"]["model_name"], "small")

    def test_scan_stability_and_end_to_end_output(self) -> None:
        self._create_installed_model("small")
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
        self.assertIn("hello world.", subtitle_path.read_text(encoding="utf-8"))

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

    @patch("app.pipeline.httpx.post")
    def test_failed_translation_requeues_then_fails(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = RuntimeError("translation down")
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

    @patch("app.pipeline.httpx.post")
    def test_openai_compatible_translation_provider(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '["你好", "世界"]'
                    }
                }
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

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
        self.assertEqual(mock_post.call_args.kwargs["json"]["model"], "gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
