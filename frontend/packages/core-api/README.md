# `@alfa-hack/core-api`

Typed HTTP port for the cabinet API. It contains no React code and follows `docs/contract.md`.

## Authentication and cabinet

- `createSession(phone)` sends `POST /api/auth/session` with `{ phone }` and returns the bearer token and user.
- `getCabinet(token)` sends `GET /api/cabinet` with `Authorization: Bearer <token>`.
- `deleteSession(token)` sends `DELETE /api/auth/session` with the bearer token.

The default API base is `http://10.193.155.238:8000/api`, matching the backend Swagger URL supplied for this project. Set `VITE_API_BASE_URL` to the backend URL including the `/api` prefix for another environment. API failures throw `ApiError` with the server's human-readable error and HTTP status.
