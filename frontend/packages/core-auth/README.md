# `@alfa-hack/core-auth`

Pure TypeScript helpers for the phone number used by the frontend. No React or browser APIs are required.

## Phone helpers

- `digitsOnly(value)` removes formatting characters.
- `formatRussianPhone(value)` formats up to ten digits as `+7 (999) 123-45-67`.
- `normalizeRussianPhone(value)` returns the backend form (`79001234567`) for a complete Russian number, or `null` for invalid input. Ten local digits and an `8` prefix are accepted.
- `isRussianPhoneComplete(value)` checks whether the value can be normalized.

The application contract accepts a numeric `phone` string in `POST /api/applications`. These helpers only prepare and validate the value; they do not send SMS or implement authentication.
