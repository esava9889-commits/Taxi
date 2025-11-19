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
        
        # Міграція 5: Система карми - видалено, колонки вже в CREATE TABLE
        
        # Міграція 6: Додати car_color до drivers
        try:
            has_car_color = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'drivers' AND column_name = 'car_color'
                )
            """)
            
            if not has_car_color:
                logger.info("🔄 Міграція drivers: додавання car_color...")
                await conn.execute("ALTER TABLE drivers ADD COLUMN car_color TEXT")
                logger.info("✅ Колонка drivers.car_color додана")
        except Exception as e:
            logger.warning(f"⚠️ Помилка міграції drivers (car_color): {e}")
        
        # Міграція 6.5: Додати priority до drivers
        try:
            has_priority = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns 
                    WHERE table_name = 'drivers' AND column_name = 'priority'
                )
            """)
            
            if not has_priority:
                logger.info("🔄 Міграція drivers: додавання priority...")
                await conn.execute("ALTER TABLE drivers ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
                logger.info("✅ Колонка drivers.priority додана")
        except Exception as e:
            logger.warning(f"⚠️ Помилка міграції drivers (priority): {e}")
        
        # Міграція 7: Система карми - видалено, колонки вже в CREATE TABLE
        
        # Міграції 8-9: Видалено, колонки вже в CREATE TABLE
        
        logger.info("✅ Міграції завершено!")
        
        # === СТВОРЕННЯ ІНДЕКСІВ ДЛЯ ПРОДУКТИВНОСТІ ===
        logger.info("🔍 Створюю індекси для оптимізації запитів...")
        
        try:
            # Індекси для orders (найчастіші запити)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_driver_id ON orders(driver_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status_user ON orders(status, user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status_driver ON orders(status, driver_id)")
            logger.info("✅ Індекси для orders створено")
            
            # Індекси для drivers
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_drivers_tg_user_id ON drivers(tg_user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_drivers_status ON drivers(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_drivers_city ON drivers(city)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_drivers_online ON drivers(online)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_drivers_status_online ON drivers(status, online)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_drivers_city_online ON drivers(city, online, status)")
            logger.info("✅ Індекси для drivers створено")
            
            # Індекси для users
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_city ON users(city)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_is_blocked ON users(is_blocked)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_role_city ON users(role, city)")
            logger.info("✅ Індекси для users створено")
            
            # Індекси для ratings
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_ratings_from_user ON ratings(from_user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_ratings_to_user ON ratings(to_user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_ratings_order_id ON ratings(order_id)")
            logger.info("✅ Індекси для ratings створено")
            
            # Індекси для payments
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_driver_id ON payments(driver_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_commission_paid ON payments(commission_paid)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_created_at ON payments(created_at)")
            logger.info("✅ Індекси для payments створено")
            
            logger.info("🎉 Всі індекси створено успішно!")
        except Exception as e:
            logger.warning(f"⚠️ Помилка створення індексів: {e}")
        
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
        
        # Додати відсутні колонки до orders якщо їх немає
        try:
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pickup_lat DOUBLE PRECISION")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pickup_lon DOUBLE PRECISION")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS dest_lat DOUBLE PRECISION")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS dest_lon DOUBLE PRECISION")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS driver_id INTEGER")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS distance_m INTEGER")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS duration_s INTEGER")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS fare_amount DOUBLE PRECISION")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS commission DOUBLE PRECISION")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS finished_at TIMESTAMP WITH TIME ZONE")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS group_message_id BIGINT")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS car_class TEXT DEFAULT 'economy'")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS tip_amount DOUBLE PRECISION")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method TEXT DEFAULT 'cash'")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancel_reason TEXT")
            logger.info("✅ Перевірено колонки orders")
        except Exception as e:
            logger.warning(f"⚠️ Помилка перевірки колонок orders: {e}")
        
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
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
                karma INTEGER NOT NULL DEFAULT 100,
                total_orders INTEGER NOT NULL DEFAULT 0,
                cancelled_orders INTEGER NOT NULL DEFAULT 0,
                bonus_rides_available INTEGER NOT NULL DEFAULT 0
            )
        """)
        
        # Додати відсутні колонки до users якщо їх немає
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS city TEXT")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'uk'")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS karma INTEGER DEFAULT 100")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_orders INTEGER DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cancelled_orders INTEGER DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_rides_available INTEGER DEFAULT 0")
            logger.info("✅ Перевірено колонки users")
        except Exception as e:
            logger.warning(f"⚠️ Помилка перевірки колонок users: {e}")
        
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
                card_number TEXT,
                car_color TEXT,
                priority INTEGER NOT NULL DEFAULT 0,
                karma INTEGER NOT NULL DEFAULT 100,
                total_orders INTEGER NOT NULL DEFAULT 0,
                rejected_orders INTEGER NOT NULL DEFAULT 0
            )
        """)
        
        # Додати відсутні колонки до drivers якщо їх немає
        try:
            await conn.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS online INTEGER DEFAULT 0")
            await conn.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS last_lat DOUBLE PRECISION")
            await conn.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS last_lon DOUBLE PRECISION")
            await conn.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE")
            await conn.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS car_class TEXT DEFAULT 'economy'")
            await conn.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS card_number TEXT")
            await conn.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS car_color TEXT")
            await conn.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 0")
            await conn.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS karma INTEGER DEFAULT 100")
            await conn.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS total_orders INTEGER DEFAULT 0")
            await conn.execute("ALTER TABLE drivers ADD COLUMN IF NOT EXISTS rejected_orders INTEGER DEFAULT 0")
            logger.info("✅ Перевірено колонки drivers")
        except Exception as e:
            logger.warning(f"⚠️ Помилка перевірки колонок drivers: {e}")
        
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
        
        # Pricing settings (налаштування ціноутворення)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pricing_settings (
                id SERIAL PRIMARY KEY,
                economy_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                standard_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1.3,
                comfort_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1.6,
                business_multiplier DOUBLE PRECISION NOT NULL DEFAULT 2.0,
                night_percent DOUBLE PRECISION NOT NULL DEFAULT 50.0,
                peak_hours_percent DOUBLE PRECISION NOT NULL DEFAULT 30.0,
                weekend_percent DOUBLE PRECISION NOT NULL DEFAULT 20.0,
                monday_morning_percent DOUBLE PRECISION NOT NULL DEFAULT 15.0,
                weather_percent DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                demand_very_high_percent DOUBLE PRECISION NOT NULL DEFAULT 40.0,
                demand_high_percent DOUBLE PRECISION NOT NULL DEFAULT 25.0,
                demand_medium_percent DOUBLE PRECISION NOT NULL DEFAULT 15.0,
                demand_low_discount_percent DOUBLE PRECISION NOT NULL DEFAULT 10.0,
                no_drivers_percent DOUBLE PRECISION NOT NULL DEFAULT 50.0,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL
            )
        """)
        logger.info("✅ Таблиця pricing_settings створена")
        
        # App settings (налаштування додатку)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        logger.info("✅ Таблиця app_settings створена")
        
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
