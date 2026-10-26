# credit

Сервис `backend`. База только своя, хост Compose — `credit-db`.

Кабинет, сессия, заявки и кредиты описаны в `docs/contract.md`. Клиент вызывает те же пути через `@alfa-hack/core-api`.

Вход только по номерам из `GET /api/demo-profiles`. Эти пользователи и их кредиты создаются при старте сервиса. Неизвестный номер не регистрируется.

## `GET /health`

Токен не нужен. Это readiness, не часть кабинетного JSON.

`200`

```json
{"status": "ok"}
```

`503` — Postgres не ответил на `SELECT 1`.

```json
{"status": "error", "reason": "db"}
```

## Кэш

`GET /api/products` и `GET /api/products/{code}` могут прийти из Redis. Форма ответа та же, что в контракте.
