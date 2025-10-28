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
    payment_card: Optional[str]
    driver_group_chat_id: Optional[int]
    driver_group_invite_link: Optional[str]
    admin_username: Optional[str]
    city_groups: dict
    city_invite_links: dict
    webapp_url: Optional[str]  # URL для WebApp з інтерактивною картою
    
# Список доступних міст (тільки 5 міст)
AVAILABLE_CITIES = [
    "Київ",
    "Дніпро",
    "Кривий Ріг",
    "Харків",
    "Одеса",
]

# Маппінг міста → ID групи водіїв
# Кожне місто має свою окрему групу для замовлень
CITY_GROUP_CHATS = {
    "Київ": None,           # Буде заповнено через ENV: KYIV_GROUP_CHAT_ID
    "Дніпро": None,         # DNIPRO_GROUP_CHAT_ID
    "Кривий Ріг": None,     # KRYVYI_RIH_GROUP_CHAT_ID
    "Харків": None,         # KHARKIV_GROUP_CHAT_ID
    "Одеса": None,          # ODESA_GROUP_CHAT_ID
}

# Маппінг міста → посилання на групу (для запрошення водіїв)
CITY_GROUP_INVITE_LINKS = {
    "Київ": None,
    "Дніпро": None,
    "Кривий Ріг": None,
    "Харків": None,
    "Одеса": None,
}


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

    admin_ids_raw = os.getenv("ADMIN_IDS", "")
    if not admin_ids_raw:
        raise RuntimeError("ADMIN_IDS is not set. Add your Telegram ID to .env")
    admin_ids = _parse_admin_ids(admin_ids_raw)

    # Database path - use /tmp for Render deployment (ephemeral but works)
    # For production, use external database or Render disk
    if os.getenv("RENDER"):
        # On Render, use /tmp (ephemeral storage)
        default_db = "/tmp/taxi.sqlite3"
    else:
        # Locally, use data/ folder
        default_db = os.path.join(os.getcwd(), "data", "taxi.sqlite3")
    
    db_path = os.getenv("DB_PATH", default_db)

    google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY") or None
    payment_card = os.getenv("PAYMENT_CARD_NUMBER") or "4149 4999 0123 4567"
    
    # Group chat ID for drivers (optional)
    driver_group_raw = os.getenv("DRIVER_GROUP_CHAT_ID")
    driver_group_chat_id = int(driver_group_raw) if driver_group_raw else None
    
    # Group invite link for drivers (optional)
    driver_group_invite_link = os.getenv("DRIVER_GROUP_INVITE_LINK") or None
    
    # Admin username for support (optional)
    admin_username = os.getenv("ADMIN_USERNAME") or None
    
    # City-specific group chats (нові ENV змінні)
    city_groups = {
        "Київ": int(os.getenv("KYIV_GROUP_CHAT_ID")) if os.getenv("KYIV_GROUP_CHAT_ID") else None,
        "Дніпро": int(os.getenv("DNIPRO_GROUP_CHAT_ID")) if os.getenv("DNIPRO_GROUP_CHAT_ID") else None,
        "Кривий Ріг": int(os.getenv("KRYVYI_RIH_GROUP_CHAT_ID")) if os.getenv("KRYVYI_RIH_GROUP_CHAT_ID") else None,
        "Харків": int(os.getenv("KHARKIV_GROUP_CHAT_ID")) if os.getenv("KHARKIV_GROUP_CHAT_ID") else None,
        "Одеса": int(os.getenv("ODESA_GROUP_CHAT_ID")) if os.getenv("ODESA_GROUP_CHAT_ID") else None,
    }
    
    # City-specific invite links
    city_invite_links = {
        "Київ": os.getenv("KYIV_GROUP_INVITE_LINK") or None,
        "Дніпро": os.getenv("DNIPRO_GROUP_INVITE_LINK") or None,
        "Кривий Ріг": os.getenv("KRYVYI_RIH_GROUP_INVITE_LINK") or None,
        "Харків": os.getenv("KHARKIV_GROUP_INVITE_LINK") or None,
        "Одеса": os.getenv("ODESA_GROUP_INVITE_LINK") or None,
    }

    # WebApp URL для інтерактивної карти (опціонально)
    webapp_url = os.getenv("WEBAPP_URL") or None
    
    # Ensure the parent directory exists (if not /tmp)
    db_dir = os.path.dirname(db_path)
    if db_dir and db_dir != "/tmp":
        os.makedirs(db_dir, exist_ok=True)

    return AppConfig(
        bot=BotConfig(token=token, admin_ids=admin_ids),
        database_path=db_path,
        google_maps_api_key=google_maps_api_key,
        payment_card=payment_card,
        driver_group_chat_id=driver_group_chat_id,  # Backward compatibility
        driver_group_invite_link=driver_group_invite_link,  # Backward compatibility
        admin_username=admin_username,
        city_groups=city_groups,
        city_invite_links=city_invite_links,
        webapp_url=webapp_url,
    )


def get_city_group_id(config: AppConfig, city: Optional[str]) -> Optional[int]:
    """
    Отримати ID групи для заданого міста.
    
    Якщо група для міста не налаштована, повертає загальну групу (fallback).
    """
    if not city:
        return config.driver_group_chat_id
    
    # Спробувати знайти city-specific групу
    city_group_id = config.city_groups.get(city)
    
    # Fallback на загальну групу
    if not city_group_id:
        return config.driver_group_chat_id
    
    return city_group_id
