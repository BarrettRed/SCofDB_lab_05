"""Event-driven cache invalidation template for LAB 05."""

from dataclasses import dataclass

from app.infrastructure.redis_client import get_redis
from app.infrastructure.cache_keys import order_card_key, catalog_key


@dataclass
class OrderUpdatedEvent:
    """Событие изменения заказа."""

    order_id: str


class CacheInvalidationEventBus:
    """
    Минимальный event bus для LAB 05.

    TODO:
    - реализовать publish/subscribe;
    - на OrderUpdatedEvent инвалидировать:
      - order_card:v1:{order_id}
      - catalog:v1 (если изменение затрагивает агрегаты каталога).
    """

    def __init__(self):
        self.redis = get_redis()

    async def publish_order_updated(self, event: OrderUpdatedEvent) -> None:
        await self.redis.delete(order_card_key(event.order_id))
        await self.redis.delete(catalog_key())