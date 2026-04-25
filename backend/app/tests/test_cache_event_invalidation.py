"""
LAB 05: Проверка починки через событийную инвалидацию.
"""

import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@db:5432/marketplace"
engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_order_card_is_fresh_after_event_invalidation():
    """
    TODO: Реализовать сценарий:
    1) Прогреть кэш карточки заказа.
    2) Изменить заказ через mutate-with-event-invalidation.
    3) Убедиться, что ключ карточки инвалидирован.
    4) Повторный GET возвращает свежие данные из БД, а не stale cache.
    """
    from app.main import app

    # Создаём тестовый заказ
    user_id = uuid.uuid4()
    order_id = uuid.uuid4()
    original_amount = 500.00
    new_amount = 999.00

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("INSERT INTO users (id, email, name, created_at) VALUES (:id, :email, :name, NOW())"),
                {"id": str(user_id), "email": f"fresh_{user_id}@example.com", "name": "Fresh Test"},
            )
            await session.execute(
                text("INSERT INTO orders (id, user_id, status, total_amount, created_at) VALUES (:id, :user_id, 'created', :amount, NOW())"),
                {"id": str(order_id), "user_id": str(user_id), "amount": original_amount},
            )

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1) Прогреваем кэш
        resp1 = await client.get(f"/api/cache-demo/orders/{order_id}/card?use_cache=true")
        assert resp1.status_code == 200
        assert resp1.json()["total_amount"] == original_amount

        # 2) Изменяем заказ С инвалидацией кэша через событие
        resp_mutate = await client.post(
            f"/api/cache-demo/orders/{order_id}/mutate-with-event-invalidation",
            json={"new_total_amount": new_amount},
        )
        assert resp_mutate.status_code == 200
        assert resp_mutate.json()["cache_invalidated"] is True

        # 3) Повторный запрос — кэш инвалидирован, получаем свежие данные из БД
        resp2 = await client.get(f"/api/cache-demo/orders/{order_id}/card?use_cache=true")
        assert resp2.status_code == 200
        fresh_amount = resp2.json()["total_amount"]

    print(f"\n✅ EVENT INVALIDATION DEMO:")
    print(f"Оригинальная сумма: {original_amount}")
    print(f"Новая сумма в БД:   {new_amount}")
    print(f"Сумма после инвалидации: {fresh_amount}")
    print(f"Данные свежие: {fresh_amount == new_amount}")

    # 4) Проверяем что получили свежие данные
    assert fresh_amount == new_amount, \
        f"Ожидали свежие данные ({new_amount}), получили {fresh_amount}"

    # Очистка
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM orders WHERE id = :id"), {"id": str(order_id)})
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(user_id)})