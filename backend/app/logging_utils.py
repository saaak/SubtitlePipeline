from __future__ import annotations

import logging

from .store import Database


def setup_logging(database: Database) -> None:
    config = database.get_config()
    level_name = str(config.get("logging", {}).get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )
