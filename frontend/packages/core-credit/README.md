# `@alfa-hack/core-credit`

Правила заявки и подписи продуктов. Без React.

Ставка, сумма и срок приходят с продукта. `presentProduct` добавляет только короткую подпись карточки.

- `presentProduct(product)` — карточка для карусели.
- `fieldLabel(field)` — подпись поля анкеты.
- `riskLabel(code)` — подпись кода риска из контракта. Незнакомый код возвращается как есть.
- `applicationStatusLabel(status, decision)` — статус заявки.
- `formatRub` / `formatCompactRub` — суммы.
- `formatIntegerInput` / `formatSignedIntegerInput` / `formatTermInput` — оставляют только цифры и группируют сумму пробелами. Срок — до трёх цифр.
- `fieldError(draft, detail, field)` и `validateDraft(draft, detail)` — проверка перед `POST /api/applications`. `null`, если значение можно отправлять.
- `toApplicationRequest(product, draft, fields, phone?)` — тело заявки. Телефон передаётся только для входа со ссылки.
