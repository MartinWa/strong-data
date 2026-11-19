# Usage

How to get a Strong CSV export into strong-data and read it back.

## Accounts

Accounts are administrator-managed; there is no public signup. Log in at
`/accounts/login/` with the credentials your administrator created. Every page
except the login form and the API reference requires a session, and every user
sees only their own imports, corrections and tokens.

## Import an export

1. **Upload** (`/upload/`) — choose the CSV file Strong exported and press
   *Preview*. The file must be a Strong export with the `Date`, `Workout Name`,
   `Exercise Name`, `Set Order`, `Weight` and `Reps` headers, and at most 10 MB.
2. **Preview** (`/preview/`) — review the session summary (date, workout,
   program, set count, volume, duration), the first 20 sets as a sample, and any
   warnings, then press *Confirm import*. The summary covers every session; only
   the set table is sampled, and confirming imports all sets.
3. **History** (`/history/`) — the imported sessions and their sets, 25 sessions
   per page.

The preview is tied to the file you uploaded: if you upload again, the old
preview is discarded and you must confirm the new one. A pending preview expires
after one hour, and the uploaded file is kept outside the session store only
until you confirm, discard or let it expire.

### Confirming replaces your existing data

Confirming an import **replaces everything you previously imported**. In one
transaction the app deletes all of your sessions, sets and exercises and inserts
the contents of the new export. This is deliberate: it makes an import
idempotent, so re-uploading the same export leaves exactly the same data instead
of duplicating it.

Two consequences:

- Upload the **complete** export each time. A partial export removes everything
  that is not in it.
- Muscle-group corrections are the exception: they are stored per exercise name
  and survive re-imports, including corrections for exercises that are absent
  from the new export.

## Warnings

Some problems reject the file at upload; others are reported per row in the
preview and do not stop the import.

| Problem | Result |
| --- | --- |
| Missing required headers, empty file, unreadable CSV | Rejected at upload |
| No importable rows | Rejected at upload |
| Invalid date, missing workout and exercise name, invalid or fractional set order or reps | Row skipped, warning shown |
| Negative weight | Row skipped, warning shown |
| Invalid or out-of-range weight, distance or seconds | Value stored as null, warning shown |
| Negative distance or seconds | Value stored as null, warning shown |
| RPE outside 6.0–10.0 or not in 0.5 steps | Stored as null, warning shown |
| Duration that cannot be parsed | Stored as null |

Skipped rows are never silently dropped: each one appears in the preview's
warning list with its CSV line number. The preview shows the first 50 warnings and
reports how many more there are.

A `Weight` of `0` is treated as bodyweight, exactly like an empty `Weight`: the
set is stored with no weight, contributes no volume and appears in bodyweight
records.

## History

`/history/` lists your sessions in date order with their sets, weight, reps and
volume. It shows what is currently stored, so after a replacement import it
shows only the new export.

## Muscle groups

New exercise names get a heuristic muscle-group guess at import time. Correct any
guess on the *Muscle groups* screen (`/corrections/`); the correction applies to
that exercise name for your account and is preserved by later imports. The field
accepts any name, so you can add groups the heuristic does not know (for example
`Forearms` or `Traps`); the suggestions are offered as autocomplete. Exercises the
heuristic cannot place are grouped under `Other`.

## API tokens

The JSON API is read-only and authenticated with a bearer token. Create one on
the *Tokens* screen (`/tokens/`):

- Give the token a name; names are unique per account.
- The secret is displayed **once**, at creation. Copy it then — only a SHA-256
  hash and an 8-character display prefix are stored.
- Revoke a token at any time; revocation takes effect on the next request.
- Set an optional expiry when you create the token; the API rejects the token
  from that moment on.

Send the secret on every request:

```sh
curl -fsS -H "Authorization: Bearer <secret>" \
  https://workouts.example.com/api/v1/summary
```

`GET /api/v1/healthz` is the only anonymous endpoint. The endpoint-by-endpoint
contract is in `docs/api.md`; the generated OpenAPI schema is at
`/api/v1/openapi.json` and also requires the token. The human-readable API
reference page at `/api-reference/` is public.

## Limits

- Uploads are capped at 10 MB.
- API collections default to `limit=50`, maximum 200; `offset` must be `>= 0`.
- API date ranges must satisfy `start <= end` and span at most about five years.
- Invalid API parameters return `422` with the error envelope; nothing is
  silently clamped.
