from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .model_manager import ModelManager
from .pipeline import PipelineError, get_translation_provider
from .runtime import ScannerService, WorkerService
from .store import Database


class ConfigUpdateRequest(BaseModel):
    file: dict[str, Any] | None = None
    processing: dict[str, Any] | None = None
    whisper: dict[str, Any] | None = None
    translation: dict[str, Any] | None = None
    subtitle: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None


class TaskActionResponse(BaseModel):
    id: int
    status: str
    stage: str
    progress: float
    cancel_requested: bool


class ScanResponse(BaseModel):
    scanned: int
    queued: int
    skipped: int


class TranslationTestRequest(BaseModel):
    enabled: bool = True
    api_base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: int = 30
    target_language: str = "zh-CN"


class SetupCompleteRequest(BaseModel):
    setup_complete: bool = True


def resolve_db_path() -> str:
    return os.environ.get("SUBPIPELINE_DB_PATH", "/config/subpipeline.db")


def resolve_frontend_dist() -> Path:
    return Path(os.environ.get("SUBPIPELINE_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))


def resolve_models_dir() -> str:
    return os.environ.get("SUBPIPELINE_MODELS_DIR", "/models")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = Database(resolve_db_path())
    database.initialize()
    app.state.database = database
    app.state.model_manager = ModelManager(resolve_models_dir())
    yield


def get_database(app: FastAPI) -> Database:
    return app.state.database


def get_model_manager(app: FastAPI) -> ModelManager:
    return app.state.model_manager


def create_app() -> FastAPI:
    app = FastAPI(title="SubPipeline", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    frontend_dist = resolve_frontend_dist()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/tasks")
    def list_tasks(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        status: str | None = Query(None),
    ) -> dict[str, Any]:
        database = get_database(app)
        result = database.list_tasks(page=page, page_size=page_size, status=status)
        return {
            "items": result.items,
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
        }

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: int) -> dict[str, Any]:
        database = get_database(app)
        task = database.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        return task

    @app.post("/api/tasks/{task_id}/cancel", response_model=TaskActionResponse)
    def cancel_task(task_id: int) -> TaskActionResponse:
        database = get_database(app)
        task = database.request_cancel(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found or not processing")
        return TaskActionResponse(
            id=task["id"],
            status=task["status"],
            stage=task["stage"],
            progress=task["progress"],
            cancel_requested=bool(task["cancel_requested"]),
        )

    @app.post("/api/tasks/{task_id}/retry", response_model=TaskActionResponse)
    def retry_task(task_id: int) -> TaskActionResponse:
        database = get_database(app)
        task = database.request_retry(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found or not retryable")
        return TaskActionResponse(
            id=task["id"],
            status=task["status"],
            stage=task["stage"],
            progress=task["progress"],
            cancel_requested=bool(task["cancel_requested"]),
        )

    @app.get("/api/tasks/{task_id}/logs")
    def get_task_logs(
        task_id: int,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        database = get_database(app)
        task = database.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        result = database.get_logs(task_id=task_id, page=page, page_size=page_size)
        return {
            "items": result.items,
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
        }

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        database = get_database(app)
        return database.get_config()

    @app.put("/api/config")
    def update_config(request: ConfigUpdateRequest) -> dict[str, Any]:
        database = get_database(app)
        payload = request.model_dump(exclude_none=True)
        try:
            return database.update_config(payload)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/system/status")
    def get_system_status() -> dict[str, Any]:
        database = get_database(app)
        model_manager = get_model_manager(app)
        config = database.get_config()
        system_status = database.get_system_status()
        return {
            **system_status,
            "asr_ready": model_manager.has_model(str(config["whisper"]["model_name"])),
            "current_model": config["whisper"]["model_name"],
        }

    @app.post("/api/system/setup-complete")
    def set_setup_complete(request: SetupCompleteRequest) -> dict[str, Any]:
        database = get_database(app)
        updated = database.set_setup_complete(request.setup_complete)
        config = database.get_config()
        model_manager = get_model_manager(app)
        return {
            **updated,
            "asr_ready": model_manager.has_model(str(config["whisper"]["model_name"])),
            "current_model": config["whisper"]["model_name"],
        }

    @app.post("/api/translation/test")
    def test_translation(request: TranslationTestRequest) -> dict[str, Any]:
        if not request.enabled:
            return {"success": True, "message": "翻译已禁用，跳过连接测试"}
        try:
            provider = get_translation_provider(
                {
                    "translation": {
                        "enabled": True,
                        "api_base_url": request.api_base_url,
                        "api_key": request.api_key,
                        "model": request.model,
                        "timeout_seconds": request.timeout_seconds,
                    }
                }
            )
            provider.translate_batch(["connection check"], request.target_language)
        except Exception as exc:
            return {"success": False, "message": str(exc)}
        return {"success": True, "message": "翻译服务连接成功"}

    @app.get("/api/models")
    def list_models() -> dict[str, Any]:
        database = get_database(app)
        model_manager = get_model_manager(app)
        config = database.get_config()
        return {
            "items": model_manager.list_models(str(config["whisper"]["model_name"])),
            "current_model": config["whisper"]["model_name"],
        }

    @app.post("/api/models/{name}/download", status_code=202)
    def download_model(name: str) -> dict[str, str]:
        model_manager = get_model_manager(app)
        try:
            model_manager.start_download(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"message": f"模型 {name} 下载已启动"}

    @app.delete("/api/models/{name}")
    def delete_model(name: str) -> dict[str, str]:
        database = get_database(app)
        model_manager = get_model_manager(app)
        config = database.get_config()
        try:
            model_manager.delete_model(name, str(config["whisper"]["model_name"]))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"message": f"模型 {name} 已删除"}

    @app.post("/api/models/{name}/activate")
    def activate_model(name: str) -> dict[str, Any]:
        database = get_database(app)
        model_manager = get_model_manager(app)
        if not model_manager.has_model(name):
            raise HTTPException(status_code=400, detail="模型尚未安装，无法切换")
        try:
            updated = database.update_config({"whisper": {"model_name": name}})
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "message": f"当前模型已切换为 {name}",
            "config": updated,
        }

    @app.post("/api/admin/scans/run", response_model=ScanResponse)
    def run_scan_once() -> ScanResponse:
        database = get_database(app)
        result = ScannerService(database).scan_once()
        return ScanResponse(scanned=result.scanned, queued=result.queued, skipped=result.skipped)

    @app.post("/api/admin/work/run-next")
    def run_next_task() -> dict[str, bool]:
        database = get_database(app)
        processed = WorkerService(database).process_next_task()
        return {"processed": processed}

    if frontend_dist.exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str):
            candidate = frontend_dist / full_path
            if full_path and candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            index_path = frontend_dist / "index.html"
            if index_path.exists():
                return FileResponse(index_path)
            raise HTTPException(status_code=404, detail="frontend not built")

    return app


app = create_app()
