"""Helper функції для роботи тільки з SQLite"""

def is_postgres() -> bool:
    """Завжди False, бо використовується лише SQLite"""
    return False