"""Helper функції для роботи з SQLite та PostgreSQL"""
import os


def is_postgres() -> bool:
    """Перевірити чи використовується PostgreSQL"""
    database_url = os.getenv("DATABASE_URL", "")
    return database_url.startswith("postgres")
