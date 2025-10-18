"""Ініціалізація PostgreSQL бази даних"""
import asyncpg
import logging

logger = logging.getLogger(__name__)


async def init_postgres_db(database_url: str) -> None:
    """Створити всі таблиці в PostgreSQL"""
    
    # Замінити postgres:// на postgresql:// для asyncpg
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    conn = await asyncpg.connect(database_url)
    
    try:
        logger.info("🐘 Створюю таблиці в PostgreSQL...")
        
        # Збережені адреси
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS saved_addresses (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                name TEXT NOT NULL,
                emoji TEXT NOT NULL DEFAULT '📍',
                address TEXT NOT NULL,
                lat DOUBLE PRECISION,
                lon DOUBLE PRECISION,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        
        # Замовлення
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                pickup_address TEXT NOT NULL,
                destination_address TEXT NOT NULL,
                comment TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                pickup_lat DOUBLE PRECISION,
                pickup_lon DOUBLE PRECISION,
                dest_lat DOUBLE PRECISION,
                dest_lon DOUBLE PRECISION,
                driver_id INTEGER,
                distance_m INTEGER,
                duration_s INTEGER,
                fare_amount DOUBLE PRECISION,
                commission DOUBLE PRECISION,
                status TEXT NOT NULL DEFAULT 'pending',
                started_at TIMESTAMP WITH TIME ZONE,
                finished_at TIMESTAMP WITH TIME ZONE,
                group_message_id BIGINT,
                car_class TEXT NOT NULL DEFAULT 'economy',
                tip_amount DOUBLE PRECISION,
                payment_method TEXT NOT NULL DEFAULT 'cash',
                cancel_reason TEXT
            )
        """)
        
        # Тарифи
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tariffs (
                id SERIAL PRIMARY KEY,
                base_fare DOUBLE PRECISION NOT NULL,
                per_km DOUBLE PRECISION NOT NULL,
                per_minute DOUBLE PRECISION NOT NULL,
                minimum DOUBLE PRECISION NOT NULL,
                commission_percent DOUBLE PRECISION NOT NULL DEFAULT 0.02,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        
        # Користувачі
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                role TEXT NOT NULL,
                city TEXT,
                language TEXT NOT NULL DEFAULT 'uk',
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        
        # Водії
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS drivers (
                id SERIAL PRIMARY KEY,
                tg_user_id BIGINT NOT NULL,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                car_make TEXT NOT NULL,
                car_model TEXT NOT NULL,
                car_plate TEXT NOT NULL,
                license_photo_file_id TEXT,
                city TEXT,
                status TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
                online INTEGER NOT NULL DEFAULT 0,
                last_lat DOUBLE PRECISION,
                last_lon DOUBLE PRECISION,
                last_seen_at TIMESTAMP WITH TIME ZONE,
                car_class TEXT NOT NULL DEFAULT 'economy',
                card_number TEXT
            )
        """)
        
        # Відхилені водії для замовлення
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS order_rejected_drivers (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                driver_id INTEGER NOT NULL REFERENCES drivers(id),
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        
        # Рейтинги водіїв
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                driver_user_id BIGINT NOT NULL,
                rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
                comment TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        
        # Рейтинги клієнтів
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS client_ratings (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                client_id BIGINT NOT NULL,
                rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
                comment TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        
        # Реферальні коди
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_codes (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                code TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        
        # Реферальні використання
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_usages (
                id SERIAL PRIMARY KEY,
                referrer_user_id BIGINT NOT NULL,
                referred_user_id BIGINT NOT NULL,
                code TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        
        # Промокоди
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id SERIAL PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                discount_percent DOUBLE PRECISION NOT NULL,
                max_uses INTEGER,
                current_uses INTEGER NOT NULL DEFAULT 0,
                valid_from TIMESTAMP WITH TIME ZONE,
                valid_until TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                created_by BIGINT NOT NULL
            )
        """)
        
        # Використані промокоди
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS promo_code_usages (
                id SERIAL PRIMARY KEY,
                promo_code_id INTEGER NOT NULL REFERENCES promo_codes(id),
                user_id BIGINT NOT NULL,
                order_id INTEGER REFERENCES orders(id),
                used_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        
        # Платежі (комісії)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                driver_tg_id BIGINT NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                payment_type TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                note TEXT
            )
        """)
        
        # Індекси для оптимізації
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_driver_id ON orders(driver_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_drivers_status ON drivers(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_drivers_online ON drivers(online)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_drivers_tg_user_id ON drivers(tg_user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id)")
        
        logger.info("✅ Всі таблиці PostgreSQL створено!")
        
    finally:
        await conn.close()
