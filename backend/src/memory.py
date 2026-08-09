import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).resolve().parent.parent / "krishi_vani_memory.db"


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS farmers (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                language_preference TEXT,
                crops_grown TEXT,
                land_size TEXT,
                district TEXT,
                irrigation_type TEXT,
                last_interaction TEXT NOT NULL
            )
            """
        )
        connection.commit()


def get_farmer(user_id: str) -> Optional[dict]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM farmers
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def save_farmer(
    user_id: str,
    name: str,
    language_preference: Optional[str] = None,
    crops_grown: Optional[str] = None,
    land_size: Optional[str] = None,
    district: Optional[str] = None,
    irrigation_type: Optional[str] = None,
) -> None:
    last_interaction = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO farmers (
                user_id,
                name,
                language_preference,
                crops_grown,
                land_size,
                district,
                irrigation_type,
                last_interaction
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name,
                language_preference = COALESCE(
                    excluded.language_preference,
                    farmers.language_preference
                ),
                crops_grown = COALESCE(
                    excluded.crops_grown,
                    farmers.crops_grown
                ),
                land_size = COALESCE(
                    excluded.land_size,
                    farmers.land_size
                ),
                district = COALESCE(
                    excluded.district,
                    farmers.district
                ),
                irrigation_type = COALESCE(
                    excluded.irrigation_type,
                    farmers.irrigation_type
                ),
                last_interaction = excluded.last_interaction
            """,
            (
                user_id,
                name,
                language_preference,
                crops_grown,
                land_size,
                district,
                irrigation_type,
                last_interaction,
            ),
        )
        connection.commit()