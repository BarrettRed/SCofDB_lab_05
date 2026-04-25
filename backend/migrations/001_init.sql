-- ============================================
-- Схема базы данных маркетплейса
-- ============================================

-- Включаем расширение UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- TODO: Создать таблицу order_statuses
-- Столбцы: status (PK), description
CREATE TABLE order_statuses (
    status      VARCHAR(20) PRIMARY KEY,
    description TEXT
);

-- TODO: Вставить значения статусов
-- created, paid, cancelled, shipped, completed
INSERT INTO order_statuses (status, description) VALUES
    ('created',   'Заказ создан'),
    ('paid',      'Заказ оплачен'),
    ('cancelled', 'Заказ отменён'),
    ('shipped',   'Заказ отправлен'),
    ('completed', 'Заказ завершён');

-- TODO: Создать таблицу users
-- Столбцы: id (UUID PK), email, name, created_at
-- Ограничения:
--   - email UNIQUE
--   - email NOT NULL и не пустой
--   - email валидный (regex через CHECK)
CREATE TABLE users (
    id         UUID          PRIMARY KEY DEFAULT uuid_generate_v4(),
    email      VARCHAR(255)  NOT NULL UNIQUE,
    name       VARCHAR(255)  NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT email_not_empty CHECK (email <> ''),
    CONSTRAINT email_valid CHECK (email ~* '^[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9\-.]+$')
);

-- TODO: Создать таблицу orders
-- Столбцы: id (UUID PK), user_id (FK), status (FK), total_amount, created_at
-- Ограничения:
--   - user_id -> users(id)
--   - status -> order_statuses(status)
--   - total_amount >= 0
CREATE TABLE orders (
    id           UUID          PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id      UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status       VARCHAR(20)   NOT NULL REFERENCES order_statuses(status),
    total_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT total_amount_non_negative CHECK (total_amount >= 0)
);

-- TODO: Создать таблицу order_items
-- Столбцы: id (UUID PK), order_id (FK), product_name, price, quantity
-- Ограничения:
--   - order_id -> orders(id) CASCADE
--   - price >= 0
--   - quantity > 0
--   - product_name не пустой
CREATE TABLE order_items (
    id           UUID          PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id     UUID          NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_name VARCHAR(255)  NOT NULL,
    price        NUMERIC(12,2) NOT NULL,
    quantity     INTEGER       NOT NULL,
    CONSTRAINT product_name_not_empty CHECK (product_name <> ''),
    CONSTRAINT price_non_negative     CHECK (price >= 0),
    CONSTRAINT quantity_positive      CHECK (quantity > 0)
);

-- TODO: Создать таблицу order_status_history
-- Столбцы: id (UUID PK), order_id (FK), status (FK), changed_at
-- Ограничения:
--   - order_id -> orders(id) CASCADE
--   - status -> order_statuses(status)
CREATE TABLE order_status_history (
    id         UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id   UUID        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    status     VARCHAR(20) NOT NULL REFERENCES order_statuses(status),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- КРИТИЧЕСКИЙ ИНВАРИАНТ: Нельзя оплатить заказ дважды
-- ============================================
-- В lab_02 триггер намеренно отключён для демонстрации race condition.
-- Защита реализована на уровне кода через REPEATABLE READ + FOR UPDATE.

-- ============================================
-- БОНУС (опционально)
-- ============================================
-- TODO: Триггер автоматического пересчета total_amount
-- TODO: Триггер автоматической записи в историю при изменении статуса
-- TODO: Триггер записи начального статуса при создании заказа