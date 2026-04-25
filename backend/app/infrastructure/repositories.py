"""Реализация репозиториев с использованием SQLAlchemy."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.user import User
from app.domain.order import Order, OrderItem, OrderStatus, OrderStatusChange


class UserRepository:
    """Репозиторий для User."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # TODO: Реализовать save(user: User) -> None
    # Используйте INSERT ... ON CONFLICT DO UPDATE
    async def save(self, user: User) -> None:
        await self.session.execute(
            text("""
                INSERT INTO users (id, email, name, created_at)
                VALUES (:id, :email, :name, :created_at)
                ON CONFLICT (id) DO UPDATE
                SET email = EXCLUDED.email,
                    name = EXCLUDED.name
            """),
            {
                "id": str(user.id),
                "email": user.email,
                "name": user.name,
                "created_at": user.created_at,
            },
        )
        
    # TODO: Реализовать find_by_id(user_id: UUID) -> Optional[User]
    async def find_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        result = await self.session.execute(
            text("SELECT id, email, name, created_at FROM users WHERE id = :id"),
            {"id": str(user_id)},
        )
        row = result.fetchone()
        if not row:
            return None
        return User(
            id=uuid.UUID(str(row.id)),
            email=row.email,
            name=row.name,
            created_at=row.created_at,
        )
        
    # TODO: Реализовать find_by_email(email: str) -> Optional[User]
    async def find_by_email(self, email: str) -> Optional[User]:
        result = await self.session.execute(
            text("SELECT id, email, name, created_at FROM users WHERE email = :email"),
            {"email": email},
        )
        row = result.fetchone()
        if not row:
            return None
        return User(
            id=uuid.UUID(str(row.id)),
            email=row.email,
            name=row.name,
            created_at=row.created_at,
        )
        
    # TODO: Реализовать find_all() -> List[User]
    async def find_all(self) -> List[User]:
        result = await self.session.execute(
            text("SELECT id, email, name, created_at FROM users ORDER BY created_at")
        )
        return [
            User(
                id=uuid.UUID(str(row.id)),
                email=row.email,
                name=row.name,
                created_at=row.created_at,
            )
            for row in result.fetchall()
        ]

class OrderRepository:
    """Репозиторий для Order."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # TODO: Реализовать save(order: Order) -> None
    # Сохранить заказ, товары и историю статусов
    async def save(self, order: Order) -> None:
        await self.session.execute(
            text("""
                INSERT INTO orders (id, user_id, status, total_amount, created_at)
                VALUES (:id, :user_id, :status, :total_amount, :created_at)
                ON CONFLICT (id) DO UPDATE
                SET status = EXCLUDED.status,
                    total_amount = EXCLUDED.total_amount
            """),
            {
                "id": str(order.id),
                "user_id": str(order.user_id),
                "status": order.status.value,
                "total_amount": str(order.total_amount),
                "created_at": order.created_at,
            },
        )
        for item in order.items:
            await self.session.execute(
                text("""
                    INSERT INTO order_items (id, order_id, product_name, price, quantity)
                    VALUES (:id, :order_id, :product_name, :price, :quantity)
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": str(item.id),
                    "order_id": str(order.id),
                    "product_name": item.product_name,
                    "price": str(item.price),
                    "quantity": item.quantity,
                },
            )
        for change in order.status_history:
            await self.session.execute(
                text("""
                    INSERT INTO order_status_history (id, order_id, status, changed_at)
                    VALUES (:id, :order_id, :status, :changed_at)
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": str(change.id),
                    "order_id": str(order.id),
                    "status": change.status.value,
                    "changed_at": change.changed_at,
                },
            )

    # TODO: Реализовать find_by_id(order_id: UUID) -> Optional[Order]
    # Загрузить заказ со всеми товарами и историей
    # Используйте object.__new__(Order) чтобы избежать __post_init__
    async def find_by_id(self, order_id: uuid.UUID) -> Optional[Order]:
        result = await self.session.execute(
            text("SELECT id, user_id, status, total_amount, created_at FROM orders WHERE id = :id"),
            {"id": str(order_id)},
        )
        row = result.fetchone()
        if not row:
            return None
        return await self._load_order(row)
    
    # TODO: Реализовать find_by_user(user_id: UUID) -> List[Order]
    async def find_by_user(self, user_id: uuid.UUID) -> List[Order]:
        result = await self.session.execute(
            text("SELECT id, user_id, status, total_amount, created_at FROM orders WHERE user_id = :user_id ORDER BY created_at"),
            {"user_id": str(user_id)},
        )
        return [await self._load_order(row) for row in result.fetchall()]
    
    # TODO: Реализовать find_all() -> List[Order]
    async def find_all(self) -> List[Order]:
        result = await self.session.execute(
            text("SELECT id, user_id, status, total_amount, created_at FROM orders ORDER BY created_at")
        )
        return [await self._load_order(row) for row in result.fetchall()]

    async def _load_order(self, row) -> Order:
        order = object.__new__(Order)
        order.id = uuid.UUID(str(row.id))
        order.user_id = uuid.UUID(str(row.user_id))
        order.status = OrderStatus(row.status)
        order.total_amount = Decimal(str(row.total_amount))
        order.created_at = row.created_at

        items_result = await self.session.execute(
            text("SELECT id, order_id, product_name, price, quantity FROM order_items WHERE order_id = :order_id"),
            {"order_id": str(order.id)},
        )
        order.items = [
            OrderItem(
                id=uuid.UUID(str(r.id)),
                order_id=uuid.UUID(str(r.order_id)),
                product_name=r.product_name,
                price=Decimal(str(r.price)),
                quantity=r.quantity,
            )
            for r in items_result.fetchall()
        ]

        history_result = await self.session.execute(
            text("SELECT id, order_id, status, changed_at FROM order_status_history WHERE order_id = :order_id ORDER BY changed_at"),
            {"order_id": str(order.id)},
        )
        order.status_history = [
            OrderStatusChange(
                id=uuid.UUID(str(r.id)),
                order_id=uuid.UUID(str(r.order_id)),
                status=OrderStatus(r.status),
                changed_at=r.changed_at,
            )
            for r in history_result.fetchall()
        ]
        return order