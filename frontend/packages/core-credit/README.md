# `@alfa-hack/core-credit`

Правила заявки и подписи продуктов. Без React.

Продукт с API — это `code` и `title`. `presentProduct` добавляет короткую подпись карточки: ставка 20%, ступень лимита до 2 000 000 ₽, срок 1–360 месяцев. Это не ответ сервера.

- `presentProduct(product)` — карточка для карусели.
- `fieldLabel(field)` — подпись поля анкеты.
- `riskLabel(code)` — подпись кода риска из контракта. Незнакомый код возвращается как есть.
- `applicationStatusLabel(status, decision)` — статус заявки.
- `formatRub` / `formatCompactRub` — суммы.
- `validateDraft(draft, fields)` — проверка перед `POST /api/applications`. `null`, если черновик можно отправлять.
- `toApplicationRequest(product, draft, fields, phone?)` — тело заявки. Телефон передаётся только для входа со ссылки.
