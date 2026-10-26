# `@alfa-hack/core-api`

Typed HTTP client for the Alfa Hack backend. The client follows the live Swagger paths under `/api` and contains no React code.

## Authentication

- `sendSmsCode(phone)` sends `POST /auth/sms/send` and returns `status`, `code`, and `message`.
- `createSession(phone, code)` sends `POST /auth/session` with both fields and returns the session and user.
- `deleteSession(token)` sends `DELETE /auth/session` with a bearer token.
- `getCurrentUser(token)` loads `GET /me`.

## Dashboard and credit flow

- `getProducts()` loads `GET /products` and returns typed product descriptions, badges, rates, amount limits, and term limits; `getProductDetail(code)` loads `GET /products/{code}` and adds the product-specific fields required for an application.
- `getApplications(token)` and `getCredits(token)` load the user's lists.
- `getApplicationDetail(token, id)` and `getCreditDetail(token, id)` load individual records.
- `createApplication(token, input)` sends `POST /applications`.
- `confirmApplication(token, id, input)` sends `POST /applications/{id}/confirm`.
- `getDashboardData(token)` composes the dashboard from `/me`, `/products`, `/applications`, and `/credits`. It does not call the aggregate `/cabinet` route.

The live OpenAPI now includes success schemas for `GET /me`, `GET /credits`, and `GET /credits/{credit_id}`. The credits list returns `{ credits: CreditShortOut[] }`; each record includes its application, product, status, amount, term, monthly payment, and creation date. Credit detail also includes the payment schedule. The client already calls both credit routes separately. `UserProfile` includes `full_name`, `role`, `email`, and the optional company profile (`inn`, `ogrn`, `name`, `short_name`, `status`, `registration_date`, `okved`, revenue, credit rating, and preapproved limit). Application and credit response types mirror the live OpenAPI schemas.

The default API base is `http://10.193.155.238:8000/api`; set `VITE_API_BASE_URL` to override it. `ApiError` carries the HTTP status and a human-readable server message when available.
