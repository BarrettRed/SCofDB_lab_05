"""
LAB 05: Демонстрация неконсистентности кэша.
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
async def test_stale_order_card_when_db_updated_without_invalidation():
    """
    TODO: Реализовать сценарий:
    1) Прогреть кэш карточки заказа (GET /api/cache-demo/orders/{id}/card?use_cache=true).
    2) Изменить заказ в БД через endpoint mutate-without-invalidation.
    3) Повторно запросить карточку с use_cache=true.
    4) Проверить, что клиент получает stale данные из кэша.
    """
    from app.main import app

    user_id = uuid.uuid4()
    order_id = uuid.uuid4()
    original_amount = 500.00
    new_amount = 999.00

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("INSERT INTO users (id, email, name, created_at) VALUES (:id, :email, :name, NOW())"),
                {"id": str(user_id), "email": f"stale_{user_id}@example.com", "name": "Stale Test"},
            )
            await session.execute(
                text("INSERT INTO orders (id, user_id, status, total_amount, created_at) VALUES (:id, :user_id, 'created', :amount, NOW())"),
                {"id": str(order_id), "user_id": str(user_id), "amount": original_amount},
            )

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.get(f"/api/cache-demo/orders/{order_id}/card?use_cache=true")
        assert resp1.status_code == 200
        cached_amount = resp1.json()["total_amount"]

        resp_mutate = await client.post(
            f"/api/cache-demo/orders/{order_id}/mutate-without-invalidation",
            json={"new_total_amount": new_amount},
        )
        assert resp_mutate.status_code == 200
        assert resp_mutate.json()["cache_invalidated"] is False

        resp2 = await client.get(f"/api/cache-demo/orders/{order_id}/card?use_cache=true")
        assert resp2.status_code == 200
        stale_amount = resp2.json()["total_amount"]

    print(f"\nSTALE CACHE DEMO:")
    print(f"Оригинальная сумма: {original_amount}")
    print(f"Новая сумма в БД:   {new_amount}")
    print(f"Сумма из кэша:      {stale_amount}")
    print(f"Кэш устарел: {stale_amount != new_amount}")

    assert stale_amount == original_amount, \
        f"Ожидали stale данные ({original_amount}), получили {stale_amount}"
    assert stale_amount != new_amount, "Кэш должен содержать устаревшие данные"

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM orders WHERE id = :id"), {"id": str(order_id)})
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(user_id)})