# Frontend

Кабинет кредита. React только в `src`. Домен — в `packages/core-*`.

```sh
npm install
npm run dev
```

`npm run dev` проксирует `/api` на `http://127.0.0.1:8000`. В Compose страница отдаётся nginx и тоже ходит в `/api`.

Вход — `POST /api/auth/session` с номером телефона. Кабинет — `GET /api/cabinet`. Заявка из кабинета создаётся черновиком и подтверждается номером. Со ссылки `/?product=working_capital` анкета уходит одним `POST /api/applications` вместе с номером.
