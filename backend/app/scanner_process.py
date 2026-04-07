from __future__ import annotations

from .logging_utils import setup_logging
from .main import resolve_db_path
from .runtime import ScannerService
from .store import Database


def main() -> None:
    database = Database(resolve_db_path(), persistent=True)
    database.initialize()
    setup_logging(database)
    database.clear_restart_required()
    ScannerService(database).run_forever()


if __name__ == "__main__":
    main()
