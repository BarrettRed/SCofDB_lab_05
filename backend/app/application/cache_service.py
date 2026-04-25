"""Cache service template for LAB 05."""

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.redis_client import get_redis
from app.infrastructure.cache_keys import catalog_key, order_card_key

CATALOG_TTL = 60      # секунд
ORDER_CARD_TTL = 30   # секунд

class CacheService:
    """
    Сервис кэширования каталога и карточки заказа.

    TODO:
    - реализовать методы через Redis client + БД;
    - добавить TTL и версионирование ключей.
    """
    def __init__(self, db: AsyncSession):
        self.db = db
        self.redis = get_redis()

    async def get_catalog(self, *, use_cache: bool = True) -> list[dict[str, Any]]:
        """
        TODO:
        1) Попытаться вернуть catalog из Redis.
        2) При miss загрузить из БД.
        3) Положить в Redis с TTL.
        """
        key = catalog_key()

        if use_cache:
            cached = await self.redis.get(key)
            if cached:
                return json.loads(cached)

        # Cache miss — загружаем из БД
        result = await self.db.execute(
            text("""
                SELECT
                    oi.product_name,
                    count(*) AS order_lines,
                    sum(oi.quantity) AS sold_qty,
                    round(avg(oi.price)::numeric, 2) AS avg_price
                FROM order_items oi
                GROUP BY oi.product_name
                ORDER BY sold_qty DESC
                LIMIT 100
            """)
        )
        rows = result.fetchall()
        data = [
            {
                "product_name": row.product_name,
                "order_lines": row.order_lines,
                "sold_qty": row.sold_qty,
                "avg_price": float(row.avg_price) if row.avg_price else 0,
            }
            for row in rows
        ]

        if use_cache:
            await self.redis.set(key, json.dumps(data), ex=CATALOG_TTL)

        return data

    async def get_order_card(self, order_id: str, *, use_cache: bool = True) -> dict[str, Any]:
        """
        TODO:
        1) Попытаться вернуть карточку заказа из Redis.
        2) При miss загрузить из БД.
        3) Положить в Redis с TTL.
        """
        key = order_card_key(order_id)

        if use_cache:
            cached = await self.redis.get(key)
            if cached:
                data = json.loads(cached)
                data["source"] = "cache"
                return data

        # Cache miss — загружаем из БД
        result = await self.db.execute(
            text("""
                SELECT id, user_id, status, total_amount, created_at
                FROM orders WHERE id = :order_id
            """),
            {"order_id": order_id},
        )
        row = result.fetchone()
        if not row:
            return None

        items_result = await self.db.execute(
            text("""
                SELECT product_name, price, quantity
                FROM order_items WHERE order_id = :order_id
            """),
            {"order_id": order_id},
        )
        items = [
            {
                "product_name": r.product_name,
                "price": float(r.price),
                "quantity": r.quantity,
            }
            for r in items_result.fetchall()
        ]

        data = {
            "id": str(row.id),
            "user_id": str(row.user_id),
            "status": row.status,
            "total_amount": float(row.total_amount),
            "created_at": str(row.created_at),
            "items": items,
            "source": "db",
        }

        if use_cache:
            # Сохраняем без поля source
            to_cache = {k: v for k, v in data.items() if k != "source"}
            await self.redis.set(key, json.dumps(to_cache), ex=ORDER_CARD_TTL)

        return data

    async def invalidate_order_card(self, order_id: str) -> None:
        """TODO: Удалить ключ карточки заказа из Redis."""
        key = order_card_key(order_id)
        await self.redis.delete(key)
        
    async def invalidate_catalog(self) -> None:
        """TODO: Удалить ключ каталога из Redis."""
        key = catalog_key()
        await self.redis.delete(key)
