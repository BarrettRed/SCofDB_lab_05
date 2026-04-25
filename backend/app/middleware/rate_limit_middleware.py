"""Rate limiting middleware template for LAB 05."""

from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.infrastructure.redis_client import get_redis
from app.infrastructure.cache_keys import payment_rate_limit_key

RATE_LIMIT_PATHS = ["/api/payments/retry-demo", "/api/payments/pay"]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis-based rate limiting для endpoint оплаты.

    Цель:
    - защита от DDoS/шторма запросов;
    - защита от случайных повторных кликов пользователя.
    """

    def __init__(self, app, limit_per_window: int = 5, window_seconds: int = 10):
        super().__init__(app)
        self.limit_per_window = limit_per_window
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        TODO: Реализовать Redis rate limiting.

        Рекомендуемая логика:
        1) Применять только к endpoint оплаты:
           - /api/orders/{order_id}/pay
           - /api/payments/retry-demo
        2) Сформировать subject:
           - user_id (если есть), иначе client IP.
        3) Использовать Redis INCR + EXPIRE:
           - key = rate_limit:pay:{subject}
           - если counter > limit_per_window -> 429 Too Many Requests.
        4) Для прохождения запроса добавить в ответ headers:
           - X-RateLimit-Limit
           - X-RateLimit-Remaining
        """

        # Заглушка: ограничение пока не применяется.
        # TODO: заменить на полноценную реализацию.
        if request.method != "POST" or request.url.path not in RATE_LIMIT_PATHS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        subject = client_ip
        key = payment_rate_limit_key(subject)

        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, self.window_seconds)

        remaining = max(0, self.limit_per_window - count)

        if count > self.limit_per_window:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
                headers={
                    "X-RateLimit-Limit": str(self.limit_per_window),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(self.window_seconds),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limit_per_window)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

