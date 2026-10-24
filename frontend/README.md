# Frontend

React + TypeScript app for the Alfa Hack credit cabinet.

## Run locally

```sh
npm install
npm run dev
```

`npm run build` creates a production build in `dist/`.

## Phone entry

The first screen collects and validates a Russian phone number. The phone utilities live in `packages/core-auth`; the React page only handles input and presentation. The current backend contract uses the number in `POST /api/applications`. It does not define a login or SMS-code endpoint, so this screen currently performs client-side validation only.
