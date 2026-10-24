# Frontend

React + TypeScript app for the Alfa Hack credit cabinet.

## Run locally

```sh
npm install
npm run dev
```

`npm run build` creates a production build in `dist/`.

## Authentication

The phone form calls `POST /api/auth/sms/send`; the confirmation form sends the entered code to `POST /api/auth/session`. For the demo backend, the SMS response provides the code shown on screen. The app stores the returned bearer token in `sessionStorage`. On sign-in and session restore, the dashboard loads the profile, products, applications, and credits from `GET /api/me`, `/api/products`, `/api/applications`, and `/api/credits` separately. Selecting a product loads its details; opening an application or credit loads that record's detail endpoint. The logout action calls `DELETE /api/auth/session` and clears the local token.

The cabinet dashboard builds the signed-in user's profile, products, applications, and credits from the individual `/api/me`, `/api/products`, `/api/applications`, and `/api/credits` routes. Its product carousel uses the live product titles, descriptions, badges, rates, and amount/term limits from `/api/products`; a separate `Помочь с выбором` action opens the first-step product-fit question.

Selecting a product loads its current requirements from `GET /api/products/{code}`. The flow intentionally stops at product selection; creating and confirming a credit application requires the amount, term, and product-specific data collected by later steps. The client exposes the create and confirm methods for those later steps.

The typed HTTP client lives in `packages/core-api`; phone formatting and validation live in `packages/core-auth`. The API base defaults to `http://10.193.155.238:8000/api`; override `VITE_API_BASE_URL` per environment. The profile uses `full_name`, `role`, `email`, and `company` when returned; the company card shows its financial indicators and registration data. Swagger still omits the user response schema.
