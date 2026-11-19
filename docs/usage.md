# Usage

How to get a Strong CSV export into strong-data and read it back.

## Accounts

Accounts are administrator-managed; there is no public signup. Log in at
`/accounts/login/` with the credentials your administrator created. Every page
except the login form requires a session, and every user
sees only their own imports, corrections and tokens.

## Get the CSV out of Strong

strong-data reads Strong's workouts CSV. Strong has no signup and no API for
this data, so the export is the only way in:

1. Open the Strong app and go to your profile or its settings screen.
2. Choose **Export workouts** (some versions label it **Export data**) and export
   the CSV.
3. Save the file, then choose it on `/upload/`; the preview opens as soon as the
   file is chosen.

The upload page carries the same three steps, so the export instructions are
available at the point of use.

## Import an export

1. **Upload** (`/upload/`) — choose the CSV file Strong exported. Choosing it
   submits the upload and opens the preview; with JavaScript off the page keeps a
   *Preview* button instead. A pick larger than 10 MB is refused in the browser,
   beside the field, before anything is sent, so the chosen file is never lost to
   a round trip. The file must be a Strong export with the `Date`, `Workout Name`,
   `Exercise Name`, `Set Order`, `Weight` and `Reps` headers, and at most 10 MB.
   Extra columns are ignored; `Duration`, `Distance`, `Seconds` and `RPE` are used
   when present. Nothing on this page talks about replacement: the import is only
   described once, on the preview page.
2. **Preview** (`/preview/`) — review the session summary (date, workout,
   program, set count, volume, duration), the first 20 sets as a sample, and any
   warnings, then press *Confirm import*. Both tables are newest first, like the
   Sessions page, so the newest session is the first row and the sample starts
   with its sets. The summary covers every session; only the set table is
   sampled, and confirming imports all sets. Sessions beyond the first 10 are
   behind *Show all* so the confirm bar stays in reach. The sticky
   bar at the bottom states what confirming replaces (`Confirming replaces 14
   sessions and 99 sets currently stored.`) or, on an empty account, that this is
   the first import.
3. **Sessions** (`/sessions/`) — the imported sessions, newest first, 25 sessions
   per page. Each row expands to show its sets.

The preview is tied to the file you uploaded: if you upload again, the old
preview is discarded and you must confirm the new one. A pending preview expires
after one hour. The uploaded file is never stored in your session; it is deleted
when you confirm or discard the preview, and expired files are swept whenever you
next upload or open the preview or sessions pages.

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

Skipped rows are never silently dropped: each one is counted in the preview's
warning list. Warnings are grouped by cause with a count, and each group expands to
the first 20 CSV line numbers plus how many further lines share that cause.

A `Weight` of `0` is treated as bodyweight, exactly like an empty `Weight`: the
set is stored with no weight, contributes no volume and appears in bodyweight
records.

## Sessions

`/sessions/` lists your sessions newest first. Each row is collapsed to the date,
workout name, program and totals; open it to see the sets with weight, reps, RPE,
volume and estimated 1RM. Sets are grouped per exercise, with the number of sets
and a set number that restarts at 1 for each exercise, so a lift performed in
several blocks reads as one group instead of duplicate rows. The program is only
shown when it differs from the workout name. It shows what is currently stored,
so after a replacement import it shows only the new export.

Three filters narrow the list: a free-text search matching the workout name or an
exercise name, a program dropdown, and an optional date range. Filters combine,
apply to whole sessions (a matched session still shows all of its sets), and are
kept when you page. Changing any control applies the filters immediately — the
search waits for a short typing pause and pauses while an input method (IME) is
composing, so Japanese, Chinese or Korean input is never interrupted — and
*Clear* removes all of them. The *Filter* button is only needed when JavaScript
is unavailable.

Search is a case-insensitive substring match on the stored names; it does not
fold scripts, so a hiragana query does not find a katakana exercise name.

`/history/` permanently redirects to `/sessions/`, keeping any query string, so
an old `/history/?page=2` bookmark still lands on the same page.

*Delete all sessions* at the bottom of the page removes every session and set
stored for your account after a second confirmation click. Muscle-group
corrections and API tokens are kept, so a later import reuses your corrections
instead of re-guessing them. There is nothing to export from the app: the Strong
CSV you imported is the export, and sending it again reproduces the data.

## Muscle groups

New exercise names get a heuristic muscle-group guess at import time. Correct any
guess on the *Muscle groups* screen (`/corrections/`); the correction applies to
that exercise name for your account and is preserved by later imports. The field
accepts any name, so you can add groups the heuristic does not know (for example
`Forearms` or `Traps`); the suggestions are offered as autocomplete. Exercises the
heuristic cannot place are grouped under `Other`. The heuristic matches English
exercise names, so names in other languages usually fall back to `Other` and are
worth correcting by hand.

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

`GET /api/v1/healthz` is the only anonymous endpoint. The generated OpenAPI
schema is at `/api/v1/openapi.json` and the Swagger UI that renders it is at
`/api/v1/docs`; both open in the browser once you are logged in, and both accept
a bearer token from a client. `docs/api.md` covers the conventions the schema
cannot express: auth, the envelope, guardrails and the derived-number
definitions.

## Limits

- Uploads are capped at 10 MB.
- API collections default to `limit=50`, maximum 200; `offset` must be `>= 0`.
- API date ranges must satisfy `start <= end` and span at most about five years.
- Invalid API parameters return `422` with the error envelope; nothing is
  silently clamped.
