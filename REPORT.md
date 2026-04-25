# Отчёт по лабораторной работе №5
## Redis-кэш, консистентность и rate limiting

**Студент:** Кучуков Алим Дахирович  
**Группа:** БПМ-22-ПО-3
**Дата:** 25.06.2026

## 1. Реализация Redis-кэша
_TODO: Опишите, что именно кэшируется и с какими ключами._

Нужно указать:
- ключ каталога;
- ключ карточки заказа;
- TTL;
- логику cache hit/miss.

Ключ: `catalog:v1`
TTL: 60 секунд
Источник данных: агрегат по таблице `order_items` — топ 100 товаров по количеству продаж

Ключ: `order_card:v1:{order_id}`
TTL: 30 секунд
Источник данных: таблицы `orders` и `order_items`


При запросе с `use_cache=true`:
1. Смотрим в Redis по ключу
2. **Cache hit** — возвращаем данные из Redis, поле `source=cache`
3. **Cache miss** — загружаем из БД, кладём в Redis с TTL, возвращаем данные с `source=db`

При запросе с `use_cache=false`:
```python
cached = await self.redis.get(key)
if cached:
    return json.loads(cached) 

data = await load_from_db()
await self.redis.set(key, json.dumps(data), ex=ORDER_CARD_TTL)
return data
```

## 2. Демонстрация неконсистентности (намеренно сломанный сценарий)
_TODO: Опишите шаги и результаты stale cache._

Минимум:
1. Прогрев кэша.
2. Изменение заказа в БД без инвалидации.
3. Повторный запрос из кэша.
4. Чем stale ответ отличается от данных в БД.

Запуск теста:
```bash
docker compose exec -T backend pytest app/tests/test_cache_stale_consistency.py -v -s
```


1. Прогрев кэша
   - Первый запрос идёт в БД, результат сохраняется в Redis с ключом `order_card:v1:{id}`
   - Сумма заказа: 500.0

2. Изменение заказа в БД без инвалидации 
   - `UPDATE orders SET total_amount = 999.0`
   - Redis ключ не удаляется
   - Ответ: `{"cache_invalidated": false, "warning": "Cache NOT invalidated"}`

3. Повторный запрос с `use_cache=true`
   - Redis возвращает закэшированные данные
   - Клиент видит старую сумму

Результат теста:
STALE CACHE DEMO:
Оригинальная сумма: 500.0
Новая сумма в БД:   999.0
Сумма из кэша:      500.0
Кэш устарел: True
PASSED


---

## 3. Починка через событийную инвалидацию
_TODO: Опишите механизм события и инвалидации._

Нужно указать:
- где генерируется событие изменения заказа;
- где обрабатывается событие;
- какие ключи инвалидируются и почему.

Запуск теста:
```bash
docker compose exec -T backend pytest app/tests/test_cache_event_invalidation.py -v -s
```


Событие генерируется в endpoint `mutate-with-event-invalidation` после успешного UPDATE в БД:
```python
event_bus = CacheInvalidationEventBus()
await event_bus.publish_order_updated(
    OrderUpdatedEvent(order_id=str(order_id))
)
```

Событие обрабатывается в классе `CacheInvalidationEventBus` в методе `publish_order_updated`:
```python
async def publish_order_updated(self, event: OrderUpdatedEvent) -> None:
    await self.redis.delete(order_card_key(event.order_id))
    await self.redis.delete(catalog_key())
```

- `order_card:v1:{order_id}` — потому что изменилась сумма конкретного заказа
- `catalog:v1` — потому что агрегат каталога может зависеть от данных заказов

**Результат теста:**
EVENT INVALIDATION DEMO:
Оригинальная сумма: 500.0
Новая сумма в БД:   999.0
Сумма после инвалидации: 999.0
Данные свежие: True
PASSED

---

## 4. Rate limiting endpoint оплаты через Redis
_TODO: Опишите реализацию лимитов._

Нужно указать:
- policy (например N запросов за M секунд);
- ключ лимита (по user_id/ip);
- поведение при превышении (`429`);
- какие заголовки возвращаются клиенту.

Запуск теста:
```bash
docker compose exec -T backend pytest app/tests/test_payment_rate_limit_redis.py -v -s
```

**Policy:** 5 запросов за 10 секунд с одного IP адреса.

**Ключ лимита:** `rate_limit:pay:{client_ip}` — по IP адресу клиента.

**Реализация через Redis INCR + EXPIRE:**
```python
count = await redis.incr(key)       
if count == 1:
    await redis.expire(key, 10)     
if count > limit:
    return JSONResponse(status_code=429, ...)
```

**Поведение при превышении:** возвращается `429 Too Many Requests` с телом:
```json
{"detail": "Too many requests. Please try again later."}
```

**Заголовки в ответе:**
- `X-RateLimit-Limit` — максимальное количество запросов в окне
- `X-RateLimit-Remaining` — сколько запросов осталось
- `Retry-After` — через сколько секунд можно повторить (при 429)

**Результат теста:**
 RATE LIMIT TEST:
Попытка 1: OK
Попытка 2: OK
Попытка 3: OK
Попытка 4: OK
Попытка 5: OK
Попытка 6: 429
Попытка 7: 429
Попытка 8: 429
Попытка 9: 429
Прошло: 5, отклонено: 4
PASSED

---

## 5. Бенчмарки RPS до/после кэша
_TODO: Приведите метрики wrk/locust._

Рекомендуемый формат:
- Endpoint: ...
- Без кэша: RPS ..., p95 latency ...
- С кэшем: RPS ..., p95 latency ...
- Изменение: +...%

Бенчмарки выполнялись через locust на 100k заказов.

### Endpoint каталога `/api/cache-demo/catalog`

| Метрика       | Без кэша (`use_cache=false`) | С кэшем (`use_cache=true`) | Изменение              |
| ------------- | ---------------------------- | -------------------------- | ---------------------- |
| RPS           | 53.2                         | 94.12                      | **1.76x**              |
| p95           | 730 ms                       | 89 ms                      | **8x**                 |


### Endpoint карточки заказа `/api/cache-demo/orders/{id}/card`

|Метрика|Без кэша (`use_cache=false`)|С кэшем (`use_cache=true`)|Изменение|
|---|---|---|---|
|RPS|29.12|49.47|**1.7x**|
|p95|691 ms|49 ms|**14x**|

---


## 6. Выводы
_TODO: Сформулируйте 3–5 практических выводов._

Рекомендуется осветить:
1. Когда кэш даёт выигрыш, а когда нет.
2. Почему инвалидация сложнее, чем кэширование.
3. Почему rate limiting полезен даже при наличии бизнес-валидаций.

-
1. Кэш даёт максимальный выигрыш для тяжёлых агрегирующих запросов. Кэш может не дать выигрыш, если данные часто обновляются в следствие чего мы все равно будем идти в основную бд, потому что будет cache miss. 
2. Инвалидация требует понимания всех зависимостей: изменение заказа может влиять на карточку заказа, на каталог, на агрегаты пользователя.
3. Бизнес-логика защищает от двойной оплаты конкретного заказа. Rate limiting решает другую задачу - он защищает инфраструктуру от DDoS, случайного цикла в коде клиента, автоматических повторов.

