from dataclasses import dataclass
from typing import List, Optional
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class BotConfig:
    token: str
    admin_ids: List[int]


@dataclass(frozen=True)
class AppConfig:
    bot: BotConfig
    database_path: str
    google_maps_api_key: Optional[str]


def _parse_admin_ids(raw: str) -> List[int]:
    ids: List[int] = []
    for part in raw.replace(',', ' ').split():
        try:
            ids.append(int(part))
        except ValueError:
            # Ignore invalid pieces silently
            continue
    return ids


def load_config() -> AppConfig:
    """
    Load configuration from environment variables. If a .env file is present,
    it will be loaded automatically via python-dotenv.

    Required:
      - BOT_TOKEN: Telegram bot token

    Optional:
      - ADMIN_IDS: space- or comma-separated list of admin user IDs
      - DB_PATH: path to SQLite DB (default: ./data/taxi.sqlite3)
    """
    load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Create .env and set BOT_TOKEN.")

    admin_ids_raw = os.getenv("ADMIN_IDS", "6828579427")
    admin_ids = _parse_admin_ids(admin_ids_raw)
    
    # Ensure the main admin is always included
    if 6828579427 not in admin_ids:
        admin_ids.append(6828579427)

    default_db = os.path.join(os.getcwd(), "data", "taxi.sqlite3")
    db_path = os.getenv("DB_PATH", default_db)

    google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY") or None

    # Ensure the parent directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    return AppConfig(
        bot=BotConfig(token=token, admin_ids=admin_ids),
        database_path=db_path,
        google_maps_api_key=google_maps_api_key,
    )
