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


def resolve_db_path() -> str:
    return os.environ.get("SUBPIPELINE_DB_PATH", "/config/subpipeline.db")


def resolve_frontend_dist() -> Path:
    return Path(os.environ.get("SUBPIPELINE_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = Database(resolve_db_path())
    database.initialize()
    app.state.database = database
    yield


def get_database(app: FastAPI) -> Database:
    return app.state.database


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
