# API

The API is read-only, versioned and owner-scoped, served at `/api/v1/`. The
generated OpenAPI schema at `GET /api/v1/openapi.json` describes every path,
parameter and response shape, and a Swagger UI renders it at `GET /api/v1/docs`;
both are also reachable from a logged-in browser. Use the schema as the reference
for fields, types and per-operation parameters. This page covers what a schema
cannot express: authentication, the response envelope, the validation guardrails
and the definitions behind each derived number.

## Auth

- `GET /api/v1/healthz` is the only anonymous endpoint.
- Every other endpoint requires `Authorization: Bearer <secret>`. The token
  resolves to a user and **every** queryset is scoped to that user; no user
  identifier appears in any URL. A missing, malformed, revoked or expired token
  returns `401` with `WWW-Authenticate: Bearer`. Only a SHA-256 hash and an
  8-character prefix are stored, and comparison is constant-time. Secrets are
  created on `/tokens/` in the web UI and shown once.
- `GET /api/v1/docs` and `GET /api/v1/openapi.json` additionally accept a
  logged-in browser session, because a browser cannot attach a bearer token. The
  data endpoints never do.

## Envelope

Every response, including errors, carries `contract_version` (the string `"1.0"`)
and `generated_at` (the UTC instant the read snapshot was taken). Additive fields
keep this version; a breaking shape change requires a new version. Every response
sets `Cache-Control: no-store`.

Collections add `items`, the complete filtered `count`, `next`/`previous`
continuation paths and `has_more`. Errors add `error` with `code`, `message` and
`details` (`details` is null when not applicable), and unmatched API URLs return
the same envelope (`404 not_found`) instead of an HTML error page. The shapes are
in the schema; the stable error codes are:

| Status | `error.code` |
| --- | --- |
| 400 | `bad_request` |
| 401 | `invalid_credentials` |
| 403 | `permission_denied` |
| 404 | `not_found` |
| 405 | `method_not_allowed` |
| 409 | `conflict` |
| 413 | `payload_too_large` |
| 415 | `unsupported_media_type` |
| 422 | `validation_error` |
| 500 | `internal_error` |
| 503 | `service_unavailable` |

Unexpected failures are `internal_error`; only transient conditions, such as a
locked database, are `service_unavailable`.

## Format

Dates are ISO `YYYY-MM-DD`; timestamps are ISO 8601 in UTC with a trailing `Z`
(for example `2026-01-05T09:00:00Z`). Numeric values are JSON numbers and missing
values are `null`, never `0`.

The export records wall-clock times without an offset, so they are absolute only
relative to the installation's `STRONG_TIME_ZONE` (default `UTC`), which is read
at import time. Two installations with different zones that import the same file
will store different UTC instants; a client should not assume the `Z` value equals
the clock in the export.

## Validation guardrails

- Integer fields reject floats, booleans and non-integer strings (so `limit=50.5`
  and `limit=true` are `422`). Boolean fields accept only the literal strings
  `true` and `false` (so `weighted=1` is `422`). Date fields must be valid
  `YYYY-MM-DD` values. Unknown query parameters, repeated query parameters,
  invalid enum values and unparseable values are `422` — including on routes that
  declare no filters, where any query parameter is `422`. No value is silently
  coerced to zero or clamped.
- `start <= end` is required and a span of more than 1830 days (about five years)
  is `422`. `limit` must be between 1 and 200 and `offset` must be `>= 0`; values
  outside those bounds are `422`, not clamped.
- Where a date range is omitted, the effective range is the span of the owner's
  data within that endpoint's other filters, or empty when there is no data.
- Aggregated endpoints return summaries; raw sets are opt-in via the raw
  endpoints.

## Collections

`items` holds the page, `count` the complete filtered total, and `next`/`previous`
are relative paths that preserve every other query parameter. `sort` takes one of
the keys the operation lists in the schema, optionally prefixed with `-` for
descending order, and always appends `id` ascending as a unique tiebreaker. The
default `limit` is 50.

## Summary

`GET /summary` returns `sessions` and `sets` (matching sessions and the sum of
their `set_count`), `volume_kg` and `volume_t` (`volume_kg / 1000`), `hours` (sum
of `duration_min`, null counting as 0, divided by 60), `sessions_per_week`
(`sessions / weeks`, where `weeks = max(effective_span_days + 1, 1) / 7`),
`avg_volume_per_session` (`volume_kg / sessions`), `avg_session_min` (total
`duration_min` / sessions) and `days_since_last_session` (`(today -
latest session_date).days`, null when there are none). All derived numbers are
rounded to two decimals, and averages are 0 when there are no sessions.

## Time series

`bucket` starts on the day, the Monday of the ISO week, the 1st of the month or
the 1st of the year. Every bucket between the effective start and end is present,
zero-filled; when both `start` and `end` are supplied the whole interval is
zero-filled even if no sessions match it.

- `sessions` counts sessions; `volume` sums set `volume_kg`; `training-time` sums
  session `duration_min / 60`; `volume-per-session` is bucket volume / bucket
  session count (0 if none).
- `moving_average=true` is valid only with `bucket=week` (otherwise `422`) and
  adds `value_4wma`: the mean of the current and previous three bucket values, or
  `null` for the first three buckets. It applies to the series `value`, not to
  group values.
- `groups` is `null` without `group_by`, otherwise one `{key, value}` entry per
  group seen in the series (missing buckets are 0). `group_by` is accepted only
  where the schema offers it: `program` on every series endpoint, `muscle` and
  `exercise` on `/series/volume`. Group values for `volume` come from set
  `volume_kg`; a set's muscle group is its exercise's `exercise_meta.muscle_group`,
  falling back to `Other`.

## Breakdowns

`count` is the number of rows before `limit` is applied, so a truncated breakdown
is detectable; `items` holds at most `limit` rows. Weekday rows are in
Monday-to-Sunday order; all other breakdowns are sorted by `volume_kg` descending,
then `key` ascending.

- `weekday`: one row per weekday name, Monday first. Sessions are counted by
  `session_date`'s weekday; `sets` and `volume_kg` come from those sessions.
- `program`: one row per program; `sets` and `volume_kg` come from those sessions.
- `muscle` / `exercises`: `sessions` is the number of distinct sessions with at
  least one matching set, `sets` the number of matching sets, and `volume_kg`
  their summed volume.

All numbers are rounded to two decimals.

## Exercise endpoints

Exercise names may contain `/`; percent-encode it in the path and the route still
resolves the full name.

- `progress` groups by `session_date`, sorted by date ascending.
  `best_est_1rm_kg` and `top_weight_kg` are `null` when the day has no weighted
  sets.
- `records` returns one row per distinct rep count, sorted by `reps` ascending.
  The row is the best set for that rep count, tie-broken by highest weight, then
  highest `est_1rm_kg`, then most recent `set_time`.
- `sets` is a paginated collection of set records (see Raw).

## Records

- `est-1rm`: one row per exercise with a non-null `est_1rm_kg`, sorted by
  `est_1rm_kg` descending. Tie-breaks: higher reps, then higher weight, then more
  recent `set_time`.
- `bodyweight`: one row per exercise with at least one bodyweight (weight null)
  set, sorted by `reps` descending. The row is the set with the most reps,
  tie-broken by most recent `set_time`.

`est_1rm_kg` is the Epley estimate, `weight_kg * (1 + reps / 30)`, deliberately
not the Brzycki formula Strong's own UI shows; no 12-rep cap is applied anywhere.

## Yearly

- `yearly` returns one row per year with data, sorted by year ascending.
- `yearly/pace` compares `year` (default: the year of `as_of`) against the same
  point in the previous year:

| Field | Meaning |
| --- | --- |
| `ytd` | `{sessions, sets, volume_kg, hours}` from Jan 1 of `year` through `as_of` |
| `last_year_to_date` | Same fields for `year - 1` through the same month/day |
| `projected` | `ytd / elapsed_days * days_in_year` for each field |
| `needed_per_week` | `max(last_year_full - ytd, 0) / remaining_weeks` for each field; 0 when no weeks remain |
| `pace` | Rows `{year, sessions, volume_kg, cumulative_sessions, cumulative_volume_kg}` for all years through `year` |

`year` must be between 2 and 9999 so that both the compared year and its
predecessor are valid; other values are `422`. The `as_of` month/day is
interpreted inside the selected year: `ytd`, `last_year_to_date`, `elapsed_days`
and the projection all use that same cutoff (clamped for leap days), so an `as_of`
from another year never compares a full year against a partial one. `elapsed_days`
includes the cutoff; `days_in_year` is 365 or 366; `remaining_weeks =
(days_in_year - elapsed_days) / 7`. Projections and weekly needs are computed from
unrounded totals; all numbers in the response are rounded to two decimals.

## Raw endpoints

With `weighted=true`, a session qualifies if it has at least one weighted set;
with `weighted=false`, only sessions whose sets are all bodyweight qualify.
`set_time` is the earliest set time in the session for session rows; session
`set_count` and `total_volume_kg` are stored at import time. `rpe` is nullable in
6.0–10.0 and never feeds any aggregate.
