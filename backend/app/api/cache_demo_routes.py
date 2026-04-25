"""Cache consistency demo endpoints for LAB 05."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import get_db
from app.application.cache_service import CacheService
from app.application.cache_events import CacheInvalidationEventBus, OrderUpdatedEvent


router = APIRouter(prefix="/api/cache-demo", tags=["cache-demo"])


class UpdateOrderRequest(BaseModel):
    """Payload для изменения заказа в demo-сценариях."""

    new_total_amount: float


@router.get("/catalog")
async def get_catalog(use_cache: bool = True, db: AsyncSession = Depends(get_db)) -> Any:
    """
    TODO: Кэш каталога товаров в Redis.

    Требования:
    1) При use_cache=true читать/писать Redis.
    2) При cache miss грузить из БД и класть в кэш.
    3) Добавить TTL.

    Примечание:
    В текущей схеме можно строить \"каталог\" как агрегат по order_items.product_name.
    """
    service = CacheService(db)
    return await service.get_catalog(use_cache=use_cache)

@router.get("/orders/{order_id}/card")
async def get_order_card(
    order_id: uuid.UUID,
    use_cache: bool = True,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    TODO: Кэш карточки заказа в Redis.

    Требования:
    1) Ключ вида order_card:v1:{order_id}.
    2) При use_cache=true возвращать данные из кэша.
    3) При miss грузить из БД и сохранять в кэш.
    """
    service = CacheService(db)
    data = await service.get_order_card(str(order_id), use_cache=use_cache)
    if not data:
        raise HTTPException(status_code=404, detail="Order not found")
    return data


@router.post("/orders/{order_id}/mutate-without-invalidation")
async def mutate_without_invalidation(
    order_id: uuid.UUID,
    payload: UpdateOrderRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    TODO: Намеренно сломанный сценарий консистентности.

    Нужно:
    1) Изменить заказ в БД.
    2) НЕ инвалидировать кэш.
    3) Показать, что последующий GET /orders/{id}/card может вернуть stale data.
    """
    async with db.begin():
        await db.execute(
            text("UPDATE orders SET total_amount = :amount WHERE id = :order_id"),
            {"amount": payload.new_total_amount, "order_id": str(order_id)},
        )

    return {
        "order_id": str(order_id),
        "new_total_amount": payload.new_total_amount,
        "cache_invalidated": False,
        "warning": "Cache NOT invalidated — stale data may be served!",
    }

@router.post("/orders/{order_id}/mutate-with-event-invalidation")
async def mutate_with_event_invalidation(
    order_id: uuid.UUID,
    payload: UpdateOrderRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    TODO: Починка через событийную инвалидацию.

    Нужно:
    1) Изменить заказ в БД.
    2) Сгенерировать событие OrderUpdated.
    3) Обработчик события должен инвалидировать связанные cache keys:
       - order_card:v1:{order_id}
       - catalog:v1 (если изменение влияет на каталог/агрегаты)
    """
    async with db.begin():
        await db.execute(
            text("UPDATE orders SET total_amount = :amount WHERE id = :order_id"),
            {"amount": payload.new_total_amount, "order_id": str(order_id)},
        )

    # Публикуем событие — инвалидирует кэш
    event_bus = CacheInvalidationEventBus()
    await event_bus.publish_order_updated(OrderUpdatedEvent(order_id=str(order_id)))

    return {
        "order_id": str(order_id),
        "new_total_amount": payload.new_total_amount,
        "cache_invalidated": True,
        "message": "Cache invalidated via event bus",
    }