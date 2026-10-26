# Фронтенд

```text
backend /api
    ▲
@alfa-hack/core-api      HTTP, без React
@alfa-hack/core-auth     номер телефона
@alfa-hack/core-credit   подписи, проверка анкеты, суммы
    ▲
frontend/src             экраны
```

Новый расчёт или правило статуса живёт в `core-*`. Экран только вызывает эти функции и рисует разметку.
