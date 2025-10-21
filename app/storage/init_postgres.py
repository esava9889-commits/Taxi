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
        
        # === МІГРАЦІЇ для існуючих таблиць ===
        logger.info("🔄 Перевіряю необхідність міграцій...")
        
        # Міграція 1: ratings - перейменувати driver_user_id на from_user_id і додати to_user_id
        try:
            # Перевірити чи існує таблиця ratings
            check = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'ratings'
                )
            """)
            
            if check:
                # Перевірити чи є стара колонка driver_user_id
                has_old_column = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'ratings' AND column_name = 'driver_user_id'
                    )
                """)
                
                has_from_user = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'ratings' AND column_name = 'from_user_id'
                    )
                """)
                
                has_to_user = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'ratings' AND column_name = 'to_user_id'
                    )
                """)
                
                if has_old_column:
                    logger.info("🔄 Міграція ratings: перейменування driver_user_id...")
                    # Перейменувати driver_user_id на to_user_id
                    await conn.execute("ALTER TABLE ratings RENAME COLUMN driver_user_id TO to_user_id")
                    logger.info("✅ Колонка driver_user_id перейменована на to_user_id")
                
                if not has_from_user:
                    logger.info("🔄 Міграція ratings: додавання from_user_id...")
                    await conn.execute("ALTER TABLE ratings ADD COLUMN from_user_id BIGINT")
                    # Скопіювати дані з to_user_id (якщо потрібно)
                    await conn.execute("UPDATE ratings SET from_user_id = to_user_id WHERE from_user_id IS NULL")
                    await conn.execute("ALTER TABLE ratings ALTER COLUMN from_user_id SET NOT NULL")
                    logger.info("✅ Колонка from_user_id додана")
        except Exception as e:
            logger.warning(f"⚠️ Помилка міграції ratings: {e}")
        
        # Міграція 2: client_ratings - додати driver_id якщо немає
        try:
            check = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'client_ratings'
                )
            """)
            
            if check:
                has_driver_id = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'client_ratings' AND column_name = 'driver_id'
                    )
                """)
                
                if not has_driver_id:
                    logger.info("🔄 Міграція client_ratings: додавання driver_id...")
                    await conn.execute("ALTER TABLE client_ratings ADD COLUMN driver_id INTEGER")
                    logger.info("✅ Колонка driver_id додана")
        except Exception as e:
            logger.warning(f"⚠️ Помилка міграції client_ratings: {e}")
        
        # Міграція 3: payments - оновити схему з старої версії
        try:
            check = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'payments'
                )
            """)
            
            if check:
                # Перевірити чи є стара структура (driver_tg_id, payment_type)
                has_old_driver_tg_id = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'payments' AND column_name = 'driver_tg_id'
                    )
                """)
                
                has_commission = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = 'payments' AND column_name = 'commission'
                    )
                """)
                
                if has_old_driver_tg_id and not has_commission:
                    logger.info("🔄 Міграція payments: оновлення структури таблиці...")
                    # Стара структура несумісна - видалити і створити заново
                    await conn.execute("DROP TABLE IF EXISTS payments CASCADE")
                    logger.info("✅ Стара таблиця payments видалена")
                elif not has_commission:
                    # Додати відсутні колонки
                    logger.info("🔄 Міграція payments: додавання відсутніх колонок...")
                    
                    has_order_id = await conn.fetchval("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns 
                            WHERE table_name = 'payments' AND column_name = 'order_id'
                        )
                    """)
                    if not has_order_id:
                        await conn.execute("ALTER TABLE payments ADD COLUMN order_id INTEGER")
                    
                    has_driver_id = await conn.fetchval("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns 
                            WHERE table_name = 'payments' AND column_name = 'driver_id'
                        )
                    """)
                    if not has_driver_id:
                        await conn.execute("ALTER TABLE payments ADD COLUMN driver_id INTEGER")
                    
                    await conn.execute("ALTER TABLE payments ADD COLUMN commission DOUBLE PRECISION")
                    await conn.execute("ALTER TABLE payments ADD COLUMN commission_paid INTEGER DEFAULT 0")
                    await conn.execute("ALTER TABLE payments ADD COLUMN payment_method TEXT")
                    await conn.execute("ALTER TABLE payments ADD COLUMN commission_paid_at TIMESTAMP WITH TIME ZONE")
                    
                    logger.info("✅ Колонки payments додані")
        except Exception as e:
            logger.warning(f"⚠️ Помилка міграції payments: {e}")
        
        # Міграція 4: tariffs - додати night_tariff_percent та weather_percent
        try:
            has_night = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'tariffs' AND column_name = 'night_tariff_percent'
                )
            """)
            
            has_weather = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'tariffs' AND column_name = 'weather_percent'
                )
            """)
            
            if not has_night:
                logger.info("🔄 Міграція tariffs: додавання night_tariff_percent...")
                await conn.execute("ALTER TABLE tariffs ADD COLUMN night_tariff_percent DOUBLE PRECISION DEFAULT 50.0")
                await conn.execute("UPDATE tariffs SET night_tariff_percent = 50.0 WHERE night_tariff_percent IS NULL")
                await conn.execute("ALTER TABLE tariffs ALTER COLUMN night_tariff_percent SET NOT NULL")
                logger.info("✅ Колонка night_tariff_percent додана")
            
            if not has_weather:
                logger.info("🔄 Міграція tariffs: додавання weather_percent...")
                await conn.execute("ALTER TABLE tariffs ADD COLUMN weather_percent DOUBLE PRECISION DEFAULT 0.0")
                await conn.execute("UPDATE tariffs SET weather_percent = 0.0 WHERE weather_percent IS NULL")
                await conn.execute("ALTER TABLE tariffs ALTER COLUMN weather_percent SET NOT NULL")
                logger.info("✅ Колонка weather_percent додана")
        except Exception as e:
            logger.warning(f"⚠️ Помилка міграції tariffs: {e}")
        
        # Міграція 5: Система карми - додати karma, total_orders, rejected_orders до drivers
        try:
            has_driver_karma = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'drivers' AND column_name = 'karma'
                )
            """)
            
            if not has_driver_karma:
                logger.info("🔄 Міграція drivers: додавання karma...")
                await conn.execute("ALTER TABLE drivers ADD COLUMN karma INTEGER DEFAULT 100")
                await conn.execute("UPDATE drivers SET karma = 100 WHERE karma IS NULL")
                await conn.execute("ALTER TABLE drivers ALTER COLUMN karma SET NOT NULL")
                logger.info("✅ Колонка drivers.karma додана")
            
            has_driver_total = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'drivers' AND column_name = 'total_orders'
                )
            """)
            
            if not has_driver_total:
                logger.info("🔄 Міграція drivers: додавання total_orders...")
                await conn.execute("ALTER TABLE drivers ADD COLUMN total_orders INTEGER DEFAULT 0")
                await conn.execute("UPDATE drivers SET total_orders = 0 WHERE total_orders IS NULL")
                await conn.execute("ALTER TABLE drivers ALTER COLUMN total_orders SET NOT NULL")
                logger.info("✅ Колонка drivers.total_orders додана")
            
            has_driver_rejected = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'drivers' AND column_name = 'rejected_orders'
                )
            """)
            
            if not has_driver_rejected:
                logger.info("🔄 Міграція drivers: додавання rejected_orders...")
                await conn.execute("ALTER TABLE drivers ADD COLUMN rejected_orders INTEGER DEFAULT 0")
                await conn.execute("UPDATE drivers SET rejected_orders = 0 WHERE rejected_orders IS NULL")
                await conn.execute("ALTER TABLE drivers ALTER COLUMN rejected_orders SET NOT NULL")
                logger.info("✅ Колонка drivers.rejected_orders додана")
        except Exception as e:
            logger.warning(f"⚠️ Помилка міграції drivers (karma): {e}")
        
        # Міграція 6: Система карми - додати karma, total_orders, cancelled_orders до users
        try:
            has_user_karma = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'users' AND column_name = 'karma'
                )
            """)
            
            if not has_user_karma:
                logger.info("🔄 Міграція users: додавання karma...")
                await conn.execute("ALTER TABLE users ADD COLUMN karma INTEGER DEFAULT 100")
                await conn.execute("UPDATE users SET karma = 100 WHERE karma IS NULL")
                await conn.execute("ALTER TABLE users ALTER COLUMN karma SET NOT NULL")
                logger.info("✅ Колонка users.karma додана")
            
            has_user_total = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'users' AND column_name = 'total_orders'
                )
            """)
            
            if not has_user_total:
                logger.info("🔄 Міграція users: додавання total_orders...")
                await conn.execute("ALTER TABLE users ADD COLUMN total_orders INTEGER DEFAULT 0")
                await conn.execute("UPDATE users SET total_orders = 0 WHERE total_orders IS NULL")
                await conn.execute("ALTER TABLE users ALTER COLUMN total_orders SET NOT NULL")
                logger.info("✅ Колонка users.total_orders додана")
            
            has_user_cancelled = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'users' AND column_name = 'cancelled_orders'
                )
            """)
            
            if not has_user_cancelled:
                logger.info("🔄 Міграція users: додавання cancelled_orders...")
                await conn.execute("ALTER TABLE users ADD COLUMN cancelled_orders INTEGER DEFAULT 0")
                await conn.execute("UPDATE users SET cancelled_orders = 0 WHERE cancelled_orders IS NULL")
                await conn.execute("ALTER TABLE users ALTER COLUMN cancelled_orders SET NOT NULL")
                logger.info("✅ Колонка users.cancelled_orders додана")
        except Exception as e:
            logger.warning(f"⚠️ Помилка міграції users (karma): {e}")
        
        logger.info("✅ Міграції завершено!")
        
        # === СТВОРЕННЯ ТАБЛИЦЬ ===
        
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
                night_tariff_percent DOUBLE PRECISION NOT NULL DEFAULT 50.0,
                weather_percent DOUBLE PRECISION NOT NULL DEFAULT 0.0,
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
                from_user_id BIGINT NOT NULL,
                to_user_id BIGINT NOT NULL,
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
                driver_id INTEGER NOT NULL,
                rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
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
                order_id INTEGER NOT NULL,
                driver_id INTEGER NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                commission DOUBLE PRECISION NOT NULL,
                commission_paid INTEGER NOT NULL DEFAULT 0,
                payment_method TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                commission_paid_at TIMESTAMP WITH TIME ZONE
            )
        """)
        
        # Tips (чайові)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tips (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL UNIQUE,
                amount DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        
        # Referrals (реферальна програма)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id SERIAL PRIMARY KEY,
                referrer_id BIGINT NOT NULL,
                referred_id BIGINT NOT NULL,
                referral_code TEXT NOT NULL,
                bonus_amount DOUBLE PRECISION NOT NULL DEFAULT 50,
                referrer_bonus DOUBLE PRECISION NOT NULL DEFAULT 30,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        
        # Rejected offers
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS rejected_offers (
                order_id INTEGER NOT NULL,
                driver_id INTEGER NOT NULL,
                rejected_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        
        # Індекси для оптимізації (з перевіркою існування колонок)
        logger.info("🔍 Створюю індекси...")
        
        # Функція для безпечного створення індексу
        async def create_index_safe(index_name: str, table: str, column: str):
            try:
                # Перевірити чи існує колонка
                exists = await conn.fetchval(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.columns 
                        WHERE table_name = '{table}' AND column_name = '{column}'
                    )
                """)
                if exists:
                    await conn.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column})")
                    logger.debug(f"✅ Індекс {index_name} створено")
                else:
                    logger.warning(f"⚠️ Колонка {table}.{column} не існує, пропускаю індекс {index_name}")
            except Exception as e:
                logger.warning(f"⚠️ Не вдалося створити індекс {index_name}: {e}")
        
        # Створити всі індекси
        await create_index_safe("idx_orders_user_id", "orders", "user_id")
        await create_index_safe("idx_orders_created_at", "orders", "created_at")
        await create_index_safe("idx_orders_status", "orders", "status")
        await create_index_safe("idx_orders_driver_id", "orders", "driver_id")
        await create_index_safe("idx_drivers_status", "drivers", "status")
        await create_index_safe("idx_drivers_online", "drivers", "online")
        await create_index_safe("idx_drivers_tg_user_id", "drivers", "tg_user_id")
        await create_index_safe("idx_users_user_id", "users", "user_id")
        await create_index_safe("idx_saved_addresses_user", "saved_addresses", "user_id")
        await create_index_safe("idx_ratings_to_user", "ratings", "to_user_id")
        await create_index_safe("idx_client_ratings", "client_ratings", "client_id")
        await create_index_safe("idx_payments_driver", "payments", "driver_id")
        await create_index_safe("idx_payments_commission_paid", "payments", "commission_paid")
        await create_index_safe("idx_referrals_referrer", "referrals", "referrer_id")
        await create_index_safe("idx_referrals_code", "referrals", "referral_code")
        
        logger.info("✅ Всі таблиці та індекси PostgreSQL створено!")
        
    finally:
        await conn.close()
