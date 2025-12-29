"""Dependency injection for the API."""

import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends

from cataloguer.database.models import Database

# Default database path from environment or current directory
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", "collection.db"))


def get_database_path() -> Path:
    """Get the database path from app state or environment."""
    return DATABASE_PATH


def get_db(db_path: Annotated[Path, Depends(get_database_path)]) -> Database:
    """Get a database instance."""
    return Database(db_path)


# Type alias for dependency injection
DbDep = Annotated[Database, Depends(get_db)]


def configure_database(db_path: Path) -> None:
    """Configure the database path at runtime."""
    global DATABASE_PATH
    DATABASE_PATH = db_path
