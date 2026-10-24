# `@alfa-hack/core-api`

Typed HTTP port for the cabinet API. It contains no React code and follows `docs/contract.md`.

## Authentication and cabinet

- `requestMockSmsCode(phone)` opens the demo confirmation step without sending an SMS.
- `verifyMockSmsCode(phone, code)` accepts the demo code `0000` for a phone with a pending demo request.
- `createSession(phone)` sends `POST /api/auth/session` with `{ phone }` and returns the bearer token and user.
- `getCabinet(token)` sends `GET /api/cabinet` with `Authorization: Bearer <token>`.
- `deleteSession(token)` sends `DELETE /api/auth/session` with the bearer token.

The SMS step is a frontend mock because the backend contract has no SMS gateway or code-verification endpoint. Replace these mock methods with the real SMS API before production use.

The default API base is `http://10.193.155.238:8000/api`, matching the backend Swagger URL supplied for this project. Set `VITE_API_BASE_URL` to the backend URL including the `/api` prefix for another environment. API failures throw `ApiError` with the server's human-readable error and HTTP status.
