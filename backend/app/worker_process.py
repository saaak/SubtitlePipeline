from __future__ import annotations

from .main import resolve_db_path
from .runtime import WorkerService
from .store import Database


def main() -> None:
    database = Database(resolve_db_path())
    database.initialize()
    database.recover_orphaned_tasks()
    database.clear_restart_required()
    WorkerService(database).run_forever()


if __name__ == "__main__":
    main()
