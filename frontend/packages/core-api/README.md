# `@alfa-hack/core-api`

HTTP-клиент кабинета. Контракт: `docs/contract.md`. React здесь нет.

База по умолчанию — `/api`. Для другого стенда задайте `VITE_API_BASE_URL`.

## Сессия

- `getDemoProfiles()` — `GET /demo-profiles`, номера без регистрации.
- `createSession(phone)` — `POST /auth/session`, тело `{ phone }`. Неизвестный номер — ошибка, пользователь не создаётся. В `user` приходят имя, роль, почта и компания.
- `deleteSession(token)` — `DELETE /auth/session`.
- `getCurrentUser(token)` — `GET /me`, в ответе `id` и `phone`.

## Кабинет и заявки

- `getCabinet(token)` — `GET /cabinet`.
- `getProducts()` — `GET /products`. У каждого продукта свои `annual_rate_pct`, сумма и срок.
- `getProductDetail(code)` — `GET /products/{code}`, те же условия плюс `fields`.
- `getApplications(token)`, `getApplicationDetail(token, id)`.
- `createApplication(token, body)` — `POST /applications`. С токеном ответ — заявка-черновик. Без токена в теле есть `phone`, ответ — `{ token, user, application }`. Отличить его можно через `isLinkApplication`.
- `confirmApplication(token, id, { phone })` — `POST /applications/{id}/confirm`.
- `getCredits(token)`, `getCreditDetail(token, id)`.

`ApiError` хранит статус и текст `error` из ответа.
