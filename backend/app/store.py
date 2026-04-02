from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .defaults import RESULT_AFFECTING_GROUPS, SYSTEM_LEVEL_FIELDS, copy_default_config


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_path(value: str) -> str:
    return str(Path(value).expanduser().resolve()).lower()


@dataclass
class PageResult:
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int


class Database:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    path_key TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    stable_hits INTEGER NOT NULL DEFAULT 1,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER,
                    file_path TEXT NOT NULL,
                    file_path_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL DEFAULT 'queued',
                    progress REAL NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    restart_required INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    config_snapshot TEXT,
                    result_payload TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    FOREIGN KEY(file_id) REFERENCES files(id)
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status_created_at ON tasks(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_file_path_key_status ON tasks(file_path_key, status);

                CREATE TABLE IF NOT EXISTS task_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_logs_task_time ON task_logs(task_id, timestamp, id);

                CREATE TABLE IF NOT EXISTS system_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_name TEXT NOT NULL,
                    key_name TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    restart_required INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(group_name, key_name)
                );
                """
            )
            defaults = copy_default_config()
            now = utc_now()
            for group_name, group_values in defaults.items():
                for key_name, value in group_values.items():
                    scope = "system" if (group_name, key_name) in SYSTEM_LEVEL_FIELDS else "runtime"
                    restart_required = 1 if scope == "system" else 0
                    connection.execute(
                        """
                        INSERT INTO system_config (group_name, key_name, value_json, scope, restart_required, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(group_name, key_name) DO NOTHING
                        """,
                        (group_name, key_name, json.dumps(value), scope, restart_required, now),
                    )

    def get_config(self) -> dict[str, Any]:
        defaults = copy_default_config()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT group_name, key_name, value_json, scope, restart_required, updated_at
                FROM system_config
                ORDER BY group_name, key_name
                """
            ).fetchall()
        restart_required = False
        for row in rows:
            defaults.setdefault(row["group_name"], {})[row["key_name"]] = json.loads(row["value_json"])
            restart_required = restart_required or bool(row["restart_required"] and row["scope"] == "system")
        defaults["meta"] = {"restart_required": restart_required}
        return defaults

    def update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        updated_system_key = False
        with self.connect() as connection:
            current = self.get_config()
            now = utc_now()
            for group_name, group_values in payload.items():
                if not isinstance(group_values, dict):
                    continue
                for key_name, value in group_values.items():
                    if group_name not in current or key_name not in current[group_name]:
                        raise KeyError(f"unknown config field: {group_name}.{key_name}")
                    scope = "system" if (group_name, key_name) in SYSTEM_LEVEL_FIELDS else "runtime"
                    restart_required = 1 if scope == "system" else 0
                    if scope == "system" and current[group_name][key_name] != value:
                        updated_system_key = True
                    connection.execute(
                        """
                        INSERT INTO system_config (group_name, key_name, value_json, scope, restart_required, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(group_name, key_name)
                        DO UPDATE SET value_json = excluded.value_json,
                                      scope = excluded.scope,
                                      restart_required = excluded.restart_required,
                                      updated_at = excluded.updated_at
                        """,
                        (group_name, key_name, json.dumps(value), scope, restart_required, now),
                    )
            if updated_system_key:
                connection.execute(
                    """
                    UPDATE system_config
                    SET restart_required = CASE WHEN scope = 'system' THEN 1 ELSE restart_required END,
                        updated_at = ?
                    """,
                    (now,),
                )
        return self.get_config()

    def clear_restart_required(self) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE system_config SET restart_required = 0 WHERE scope = 'system'"
            )

    def list_tasks(self, page: int, page_size: int, status: str | None = None) -> PageResult:
        offset = max(page - 1, 0) * page_size
        filters: list[Any] = []
        where_clause = ""
        if status:
            where_clause = "WHERE status = ?"
            filters.append(status)
        with self.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM tasks {where_clause}",
                filters,
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT id, file_path, status, stage, progress, retry_count, max_retries, cancel_requested,
                       restart_required, error_message, created_at, updated_at, started_at, finished_at
                FROM tasks
                {where_clause}
                ORDER BY updated_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                [*filters, page_size, offset],
            ).fetchall()
        return PageResult([dict(row) for row in rows], page, page_size, total)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, file_path, status, stage, progress, retry_count, max_retries, cancel_requested,
                       restart_required, error_message, config_snapshot, result_payload,
                       created_at, updated_at, started_at, finished_at
                FROM tasks
                WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
        if not row:
            return None
        task = dict(row)
        task["config_snapshot"] = json.loads(task["config_snapshot"]) if task["config_snapshot"] else None
        task["result_payload"] = json.loads(task["result_payload"]) if task["result_payload"] else None
        return task

    def get_logs(self, task_id: int, page: int, page_size: int) -> PageResult:
        offset = max(page - 1, 0) * page_size
        with self.connect() as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM task_logs WHERE task_id = ?",
                (task_id,),
            ).fetchone()[0]
            rows = connection.execute(
                """
                SELECT id, task_id, stage, level, message, details_json, timestamp
                FROM task_logs
                WHERE task_id = ?
                ORDER BY timestamp ASC, id ASC
                LIMIT ? OFFSET ?
                """,
                (task_id, page_size, offset),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item["details_json"]) if item["details_json"] else None
            item.pop("details_json", None)
            items.append(item)
        return PageResult(items, page, page_size, total)

    def log(self, task_id: int, stage: str, level: str, message: str, details: dict[str, Any] | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO task_logs (task_id, stage, level, message, details_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, stage, level, message, json.dumps(details) if details else None, utc_now()),
            )

    def request_cancel(self, task_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET cancel_requested = 1, updated_at = ?
                WHERE id = ? AND status = 'processing'
                """,
                (utc_now(), task_id),
            )
        return self.get_task(task_id)

    def request_retry(self, task_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = 'pending',
                    stage = 'queued',
                    progress = 0,
                    cancel_requested = 0,
                    error_message = NULL,
                    updated_at = ?,
                    started_at = NULL,
                    finished_at = NULL
                WHERE id = ? AND status IN ('failed', 'cancelled', 'done')
                """,
                (utc_now(), task_id),
            )
        return self.get_task(task_id)

    def observe_file(self, file_path: str, size_bytes: int, mtime: float) -> dict[str, Any]:
        path_key = normalize_path(file_path)
        now = utc_now()
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT id, size_bytes, mtime, stable_hits
                FROM files
                WHERE path_key = ?
                """,
                (path_key,),
            ).fetchone()
            if existing:
                stable_hits = existing["stable_hits"] + 1 if (
                    existing["size_bytes"] == size_bytes and float(existing["mtime"]) == float(mtime)
                ) else 1
                connection.execute(
                    """
                    UPDATE files
                    SET path = ?, size_bytes = ?, mtime = ?, stable_hits = ?, last_seen_at = ?
                    WHERE path_key = ?
                    """,
                    (file_path, size_bytes, mtime, stable_hits, now, path_key),
                )
                file_id = existing["id"]
            else:
                stable_hits = 1
                cursor = connection.execute(
                    """
                    INSERT INTO files (path, path_key, size_bytes, mtime, stable_hits, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (file_path, path_key, size_bytes, mtime, stable_hits, now, now),
                )
                file_id = cursor.lastrowid
        return {
            "file_id": file_id,
            "path": file_path,
            "path_key": path_key,
            "size_bytes": size_bytes,
            "mtime": mtime,
            "stable_hits": stable_hits,
        }

    def has_active_task(self, path_key: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM tasks
                WHERE file_path_key = ? AND status IN ('pending', 'processing')
                LIMIT 1
                """,
                (path_key,),
            ).fetchone()
        return row is not None

    def create_task(self, file_id: int, file_path: str) -> dict[str, Any]:
        config = self.get_config()
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    file_id, file_path, file_path_key, status, stage, progress, retry_count, max_retries,
                    cancel_requested, restart_required, created_at, updated_at
                )
                VALUES (?, ?, ?, 'pending', 'queued', 0, 0, ?, 0, ?, ?, ?)
                """,
                (
                    file_id,
                    file_path,
                    normalize_path(file_path),
                    int(config["processing"]["max_retries"]),
                    1 if config["meta"]["restart_required"] else 0,
                    now,
                    now,
                ),
            )
            task_id = cursor.lastrowid
        self.log(task_id, "queue", "INFO", "任务已入队", {"file_path": file_path})
        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError("failed to load created task")
        return task

    def claim_next_pending_task(self) -> dict[str, Any] | None:
        config = self.get_config()
        snapshot = {
            group_name: group_values
            for group_name, group_values in config.items()
            if group_name in RESULT_AFFECTING_GROUPS
        }
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, file_path, retry_count, max_retries
                FROM tasks
                WHERE status = 'pending'
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            connection.execute(
                """
                UPDATE tasks
                SET status = 'processing',
                    stage = 'extract_audio',
                    progress = 0,
                    config_snapshot = ?,
                    updated_at = ?,
                    started_at = COALESCE(started_at, ?)
                WHERE id = ?
                """,
                (json.dumps(snapshot), now, now, row["id"]),
            )
            task_id = row["id"]
        self.log(task_id, "processing", "INFO", "任务开始处理", {"config_snapshot": snapshot})
        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError("failed to claim pending task")
        return task

    def update_task_stage(self, task_id: int, stage: str, progress: float, status: str = "processing") -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET stage = ?, progress = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (stage, progress, status, utc_now(), task_id),
            )

    def mark_task_done(self, task_id: int, result_payload: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = 'done',
                    stage = 'output_finalize',
                    progress = 100,
                    result_payload = ?,
                    error_message = NULL,
                    updated_at = ?,
                    finished_at = ?
                WHERE id = ?
                """,
                (json.dumps(result_payload), now, now, task_id),
            )
        self.log(task_id, "output_finalize", "INFO", "任务处理完成", result_payload)

    def mark_task_cancelled(self, task_id: int, stage: str, message: str = "任务已取消") -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = 'cancelled',
                    stage = ?,
                    progress = progress,
                    error_message = ?,
                    updated_at = ?,
                    finished_at = ?
                WHERE id = ?
                """,
                (stage, message, now, now, task_id),
            )
        self.log(task_id, stage, "WARNING", message)

    def mark_task_failure(self, task_id: int, stage: str, message: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError("task not found during failure")
        retry_count = int(task["retry_count"])
        max_retries = int(task["max_retries"])
        should_retry = retry_count < max_retries
        now = utc_now()
        with self.connect() as connection:
            if should_retry:
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'pending',
                        stage = 'queued',
                        progress = 0,
                        retry_count = retry_count + 1,
                        error_message = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (message, now, task_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        stage = ?,
                        error_message = ?,
                        updated_at = ?,
                        finished_at = ?
                    WHERE id = ?
                    """,
                    (stage, message, now, now, task_id),
                )
        level = "WARNING" if should_retry else "ERROR"
        self.log(task_id, stage, level, message, {"will_retry": should_retry})
        updated = self.get_task(task_id)
        if updated is None:
            raise RuntimeError("failed to reload task after failure")
        return updated

    def is_cancel_requested(self, task_id: int) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return bool(row and row["cancel_requested"])
