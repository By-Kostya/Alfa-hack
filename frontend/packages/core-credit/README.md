# `@alfa-hack/core-credit`

Правила заявки и подписи продуктов. Без React.

Ставка, сумма и срок приходят с продукта. `presentProduct` добавляет только короткую подпись карточки.

- `presentProduct(product)` — карточка для карусели.
- `fieldLabel(field)` — подпись поля анкеты.
- `riskLabel(code)` — подпись кода риска из контракта. Незнакомый код возвращается как есть.
- `applicationStatusLabel(status, decision)` — статус заявки.
- `formatRub` / `formatCompactRub` — суммы.
- `validateDraft(draft, detail)` — проверка перед `POST /api/applications` по полям и пределам продукта. `null`, если черновик можно отправлять.
- `toApplicationRequest(product, draft, fields, phone?)` — тело заявки. Телефон передаётся только для входа со ссылки.
