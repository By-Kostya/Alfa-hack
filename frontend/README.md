# Frontend

React + TypeScript app for the Alfa Hack credit cabinet.

## Run locally

```sh
npm install
npm run dev
```

`npm run build` creates a production build in `dist/`.

## Authentication

The phone form opens a mock SMS confirmation step. Enter `0000` to pass it, then the app calls `POST /api/auth/session`, stores the returned bearer token in `sessionStorage`, and loads `GET /api/cabinet`. When the page opens with a saved token, it restores the cabinet. The logout action calls `DELETE /api/auth/session` and clears the local token.

The typed HTTP client and SMS mock live in `packages/core-api`; phone formatting and validation live in `packages/core-auth`. The API base defaults to `http://10.193.155.238:8000/api`; override `VITE_API_BASE_URL` per environment. The mock does not send a real SMS and should be replaced before production use.
