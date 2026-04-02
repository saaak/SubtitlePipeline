from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime import ScannerService, WorkerService
from app.store import Database


class SubtitlePipelineMvpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.data_dir = self.base / "data"
        self.output_dir = self.base / "output"
        self.config_dir = self.base / "config"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
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
                    "backend_mode": "mock",
                    "work_dir": str(self.config_dir / "work"),
                    "max_retries": 1,
                },
                "translation": {
                    "enabled": True,
                    "provider": "mock",
                    "target_languages": ["zh-CN"],
                    "max_retries": 1,
                    "fail_languages": [],
                },
                "subtitle": {
                    "bilingual": True,
                    "bilingual_mode": "merge",
                    "filename_template": "{stem}.{lang}.srt",
                },
            }
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_api_endpoints_cover_task_config_and_logs(self) -> None:
        frontend_dist = self.base / "frontend-dist"
        frontend_dist.mkdir(parents=True, exist_ok=True)
        (frontend_dist / "index.html").write_text("<!doctype html><title>SubPipeline</title>", encoding="utf-8")
        previous_db = os.environ.get("SUBPIPELINE_DB_PATH")
        previous_dist = os.environ.get("SUBPIPELINE_FRONTEND_DIST")
        os.environ["SUBPIPELINE_DB_PATH"] = str(self.config_dir / "api.db")
        os.environ["SUBPIPELINE_FRONTEND_DIST"] = str(frontend_dist)
        try:
            app = create_app()
            with TestClient(app) as client:
                response = client.get("/api/health")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "ok")

                update_response = client.put(
                    "/api/config",
                    json={
                        "file": {
                            "input_dir": str(self.data_dir),
                            "output_dir": str(self.output_dir),
                            "min_size_mb": 0,
                            "allowed_extensions": [".mp4"],
                        },
                        "processing": {
                            "backend_mode": "mock",
                            "work_dir": str(self.config_dir / "work"),
                            "max_retries": 1,
                        },
                    },
                )
                self.assertEqual(update_response.status_code, 200)

                video_path = self.data_dir / "api_demo.mp4"
                video_path.write_bytes(b"api-demo-video")

                first_scan = client.post("/api/admin/scans/run")
                second_scan = client.post("/api/admin/scans/run")
                self.assertEqual(first_scan.status_code, 200)
                self.assertEqual(second_scan.status_code, 200)
                self.assertEqual(second_scan.json()["queued"], 1)

                work_response = client.post("/api/admin/work/run-next")
                self.assertEqual(work_response.status_code, 200)
                self.assertTrue(work_response.json()["processed"])

                tasks_response = client.get("/api/tasks?page=1&page_size=10")
                self.assertEqual(tasks_response.status_code, 200)
                items = tasks_response.json()["items"]
                self.assertEqual(len(items), 1)
                task_id = items[0]["id"]

                detail_response = client.get(f"/api/tasks/{task_id}")
                logs_response = client.get(f"/api/tasks/{task_id}/logs?page=1&page_size=10")
                retry_response = client.post(f"/api/tasks/{task_id}/retry")

                self.assertEqual(detail_response.status_code, 200)
                self.assertEqual(logs_response.status_code, 200)
                self.assertEqual(retry_response.status_code, 200)
                self.assertGreaterEqual(logs_response.json()["total"], 1)
                self.assertEqual(retry_response.json()["status"], "pending")
        finally:
            if previous_db is None:
                os.environ.pop("SUBPIPELINE_DB_PATH", None)
            else:
                os.environ["SUBPIPELINE_DB_PATH"] = previous_db
            if previous_dist is None:
                os.environ.pop("SUBPIPELINE_FRONTEND_DIST", None)
            else:
                os.environ["SUBPIPELINE_FRONTEND_DIST"] = previous_dist

    def test_scan_stability_and_end_to_end_output(self) -> None:
        video_path = self.data_dir / "demo_video.mp4"
        video_path.write_bytes(b"demo-video-content")
        scanner = ScannerService(self.database)
        first_scan = scanner.scan_once()
        self.assertEqual(first_scan.queued, 0)
        second_scan = scanner.scan_once()
        self.assertEqual(second_scan.queued, 1)

        worker = WorkerService(self.database)
        processed = worker.process_next_task()
        self.assertTrue(processed)

        tasks = self.database.list_tasks(page=1, page_size=10).items
        self.assertEqual(len(tasks), 1)
        task = self.database.get_task(tasks[0]["id"])
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task["status"], "done")
        self.assertTrue(task["result_payload"]["subtitle_paths"])
        subtitle_path = Path(task["result_payload"]["subtitle_paths"][0])
        self.assertTrue(subtitle_path.exists())
        self.assertIn("[zh-CN]", subtitle_path.read_text(encoding="utf-8"))

        logs = self.database.get_logs(task["id"], page=1, page_size=50)
        self.assertGreaterEqual(logs.total, 6)

    def test_failed_translation_requeues_then_fails(self) -> None:
        self.database.update_config(
            {
                "translation": {
                    "enabled": True,
                    "provider": "mock",
                    "target_languages": ["zh-CN"],
                    "max_retries": 1,
                    "fail_languages": ["zh-CN"],
                }
            }
        )
        video_path = self.data_dir / "will_fail.mp4"
        video_path.write_bytes(b"demo-video-content")
        scanner = ScannerService(self.database)
        scanner.scan_once()
        scanner.scan_once()

        worker = WorkerService(self.database)
        self.assertTrue(worker.process_next_task())
        task = self.database.list_tasks(page=1, page_size=10).items[0]
        reloaded = self.database.get_task(task["id"])
        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        self.assertEqual(reloaded["status"], "pending")
        self.assertEqual(reloaded["retry_count"], 1)

        self.assertTrue(worker.process_next_task())
        failed = self.database.get_task(task["id"])
        self.assertIsNotNone(failed)
        assert failed is not None
        self.assertEqual(failed["status"], "failed")

    def test_config_snapshot_is_frozen_for_processing_task(self) -> None:
        video_path = self.data_dir / "snapshot_demo.mp4"
        video_path.write_bytes(b"demo-video-content")
        scanner = ScannerService(self.database)
        scanner.scan_once()
        scanner.scan_once()

        task = self.database.claim_next_pending_task()
        self.assertIsNotNone(task)
        assert task is not None
        snapshot_before = task["config_snapshot"]
        self.assertEqual(snapshot_before["translation"]["target_languages"], ["zh-CN"])

        self.database.update_config({"translation": {"target_languages": ["fr"]}})
        frozen_task = self.database.get_task(task["id"])
        self.assertIsNotNone(frozen_task)
        assert frozen_task is not None
        self.assertEqual(frozen_task["config_snapshot"]["translation"]["target_languages"], ["zh-CN"])


if __name__ == "__main__":
    unittest.main()
