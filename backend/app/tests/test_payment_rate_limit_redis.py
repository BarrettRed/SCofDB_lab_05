"""
LAB 05: Rate limiting endpoint оплаты через Redis.
"""

import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.redis_client import get_redis

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@db:5432/marketplace"
engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_payment_endpoint_rate_limit():
    """
    TODO: Реализовать тест.

    Рекомендуемая проверка:
    1) Сделать N запросов оплаты в пределах одного окна.
    2) Проверить, что первые <= limit проходят.
    3) Следующие запросы получают 429 Too Many Requests.
    4) Проверить заголовки X-RateLimit-Limit / X-RateLimit-Remaining.
    """
    from app.main import app

    # Создаём тестовый заказ
    user_id = uuid.uuid4()
    order_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("INSERT INTO users (id, email, name, created_at) VALUES (:id, :email, :name, NOW())"),
                {"id": str(user_id), "email": f"rl_{user_id}@example.com", "name": "RateLimit Test"},
            )
            await session.execute(
                text("INSERT INTO orders (id, user_id, status, total_amount, created_at) VALUES (:id, :user_id, 'created', 100.00, NOW())"),
                {"id": str(order_id), "user_id": str(user_id)},
            )
            await session.execute(
                text("INSERT INTO order_status_history (id, order_id, status, changed_at) VALUES (gen_random_uuid(), :order_id, 'created', NOW())"),
                {"order_id": str(order_id)},
            )

    # Очищаем Redis ключ rate limit перед тестом
    redis = get_redis()
    await redis.delete(f"rate_limit:pay:testclient")

    transport = ASGITransport(app=app)
    limit = 5  # должно совпадать с limit_per_window в RateLimitMiddleware

    results = []
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for i in range(limit + 3):  # отправляем больше чем лимит
            resp = await client.post(
                "/api/payments/retry-demo",
                json={"order_id": str(order_id), "mode": "unsafe"},
            )
            results.append({
                "attempt": i + 1,
                "status_code": resp.status_code,
                "remaining": resp.headers.get("X-RateLimit-Remaining"),
                "limit": resp.headers.get("X-RateLimit-Limit"),
            })

    passed = [r for r in results if r["status_code"] != 429]
    rejected = [r for r in results if r["status_code"] == 429]

    print(f"\n🚦 RATE LIMIT TEST:")
    for r in results:
        status = "✅" if r["status_code"] != 429 else "❌ 429"
        print(f"  Попытка {r['attempt']}: {status} | remaining={r['remaining']} | limit={r['limit']}")
    print(f"\nПрошло: {len(passed)}, отклонено: {len(rejected)}")

    # Проверки
    assert len(passed) <= limit, f"Должно пройти не более {limit} запросов"
    assert len(rejected) >= 1, "Хотя бы один запрос должен получить 429"
    assert results[0]["limit"] == str(limit), "Заголовок X-RateLimit-Limit должен быть установлен"

    # Очистка
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM order_status_history WHERE order_id = :id"), {"id": str(order_id)})
            await session.execute(text("DELETE FROM orders WHERE id = :id"), {"id": str(order_id)})
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(user_id)})