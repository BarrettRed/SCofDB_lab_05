"""Idempotency middleware template for LAB 04."""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware

from app.infrastructure.db import DATABASE_URL

# Пути на которых применяется middleware
IDEMPOTENCY_PATHS = ["/api/payments/retry-demo", "/api/payments/pay"]

engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Middleware для идемпотентности POST-запросов оплаты.

    Идея:
    - Клиент отправляет `Idempotency-Key` в header.
    - Если запрос с таким ключом уже выполнялся для того же endpoint и payload,
      middleware возвращает кэшированный ответ (без повторного списания).
    """

    def __init__(self, app, ttl_seconds: int = 24 * 60 * 60):
        super().__init__(app)
        self.ttl_seconds = ttl_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        TODO: Реализовать алгоритм.

        Рекомендуемая логика:
        1) Пропускать только целевые запросы:
           - method == POST
           - path в whitelist для платежей
        2) Читать Idempotency-Key из headers.
           Если ключа нет -> обычный call_next(request)
        3) Считать request_hash (например sha256 от body).
        4) В транзакции:
           - проверить запись в idempotency_keys
           - если completed и hash совпадает -> вернуть кэш (status_code + body)
           - если key есть, но hash другой -> вернуть 409 Conflict
           - если ключа нет -> создать запись processing
        5) Выполнить downstream request через call_next.
        6) Сохранить response в idempotency_keys со статусом completed.
        7) Вернуть response клиенту.

        Дополнительно:
        - обработайте кейс конкурентных одинаковых ключей
          (уникальный индекс + retry/select existing).
        """
        # 1) Пропускаем не-POST запросы и пути не из whitelist
        if request.method != "POST" or request.url.path not in IDEMPOTENCY_PATHS:
            return await call_next(request)

        # 2) Читаем Idempotency-Key из заголовка
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return await call_next(request)

        # 3) Читаем тело запроса и считаем hash
        raw_body = await request.body()
        request_hash = self.build_request_hash(raw_body)
        request_method = request.method
        request_path = request.url.path
        expires_at = datetime.utcnow() + timedelta(seconds=self.ttl_seconds)

        async with AsyncSessionLocal() as session:
            # 4) Проверяем существующую запись
            result = await session.execute(
                text("""
                    SELECT id, status, request_hash, status_code, response_body
                    FROM idempotency_keys
                    WHERE idempotency_key = :key
                      AND request_method = :method
                      AND request_path = :path
                """),
                {
                    "key": idempotency_key,
                    "method": request_method,
                    "path": request_path,
                },
            )
            existing = result.fetchone()

            if existing:
                # Ключ уже есть
                if existing.request_hash != request_hash:
                    # Тот же ключ но другой payload — 409 Conflict
                    return JSONResponse(
                        status_code=409,
                        content={"detail": "Idempotency key reused with different payload"},
                    )
                if existing.status == "completed":
                    # Уже выполнен — возвращаем кэш
                    return JSONResponse(
                        status_code=existing.status_code,
                        content=existing.response_body,
                        headers={"X-Idempotency-Replayed": "true"},
                    )
                # Статус processing — запрос ещё выполняется
                return JSONResponse(
                    status_code=409,
                    content={"detail": "Request is already being processed"},
                )
            else:
                # Создаём новую запись processing
                try:
                    await session.execute(
                        text("""
                            INSERT INTO idempotency_keys
                                (idempotency_key, request_method, request_path,
                                 request_hash, status, expires_at)
                            VALUES
                                (:key, :method, :path, :hash, 'processing', :expires_at)
                        """),
                        {
                            "key": idempotency_key,
                            "method": request_method,
                            "path": request_path,
                            "hash": request_hash,
                            "expires_at": expires_at,
                        },
                    )
                    await session.commit()
                except Exception:
                    # Конкурентный запрос уже создал запись — откатываемся
                    await session.rollback()
                    return JSONResponse(
                        status_code=409,
                        content={"detail": "Concurrent request with same key"},
                    )

        # 5) Выполняем downstream запрос
        # Восстанавливаем тело запроса для следующего обработчика
        async def receive():
            return {"type": "http.request", "body": raw_body}

        request._receive = receive
        response = await call_next(request)

        # 6) Читаем тело ответа
        response_body_bytes = b""
        async for chunk in response.body_iterator:
            response_body_bytes += chunk

        try:
            response_body_json = json.loads(response_body_bytes.decode())
        except Exception:
            response_body_json = {"raw": response_body_bytes.decode()}

        # 7) Сохраняем ответ в idempotency_keys
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("""
                    UPDATE idempotency_keys
                    SET status = 'completed',
                        status_code = :status_code,
                        response_body = :response_body,
                        updated_at = NOW()
                    WHERE idempotency_key = :key
                      AND request_method = :method
                      AND request_path = :path
                """),
                {
                    "status_code": response.status_code,
                    "response_body": json.dumps(response_body_json),
                    "key": idempotency_key,
                    "method": request_method,
                    "path": request_path,
                },
            )
            await session.commit()

        return Response(
            content=response_body_bytes,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
        # Текущая заглушка: middleware ничего не меняет.
        # TODO: заменить на полноценную реализацию с БД.
        # return await call_next(request)

    @staticmethod
    def build_request_hash(raw_body: bytes) -> str:
        """Стабильный хэш тела запроса для проверки reuse ключа с другим payload."""
        return hashlib.sha256(raw_body).hexdigest()

    @staticmethod
    def encode_response_payload(body_obj) -> str:
        """Сериализация response body для сохранения в idempotency_keys."""
        return json.dumps(body_obj, ensure_ascii=False)
