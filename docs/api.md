# API

The API is read-only, versioned and owner-scoped. It is served at `/api/v1/` by
django-ninja. The generated OpenAPI schema at `GET /api/v1/openapi.json`
describes every path, parameter and response field, and a Swagger UI renders it
at `GET /api/v1/docs`. Both open in a logged-in browser session and accept a
bearer token from a client.

This document deliberately does not restate the generated schema. It records only
what a schema cannot express: the authentication model, the response envelope,
the validation guardrails and the definitions behind each derived number.

## Auth

- `GET /api/v1/healthz` is the only anonymous endpoint.
- Every other API endpoint requires `Authorization: Bearer <secret>`. The token
  is resolved to a user and **every** queryset is scoped to that user; no user
  identifier appears in any URL. A missing, malformed, revoked or expired token
  returns `401` with `WWW-Authenticate: Bearer`. Only SHA-256 token hashes and an
  8-character prefix are stored; comparison is constant-time. Secrets are created
  in the web UI and shown once.
- `GET /api/v1/docs` and `GET /api/v1/openapi.json` additionally accept a
  logged-in browser session, because a browser cannot attach a bearer token. The
  data endpoints never do.

## Envelope

Success (single resource or aggregate):

```json
{"contract_version": "1.0", "generated_at": "2026-01-05T09:00:00Z", "...": "..."}
```

Success (collection):

```json
{
  "contract_version": "1.0",
  "generated_at": "2026-01-05T09:00:00Z",
  "items": [],
  "count": 0,
  "next": null,
  "previous": null,
  "has_more": false
}
```

Every response, including errors, carries `contract_version` (the string `"1.0"`)
and `generated_at` (the UTC instant the read snapshot was taken). Additive fields
keep this version; a breaking shape change requires a new version. Every response
sets `Cache-Control: no-store`.

## Errors

```json
{
  "contract_version": "1.0",
  "generated_at": "2026-01-05T09:00:00Z",
  "error": {"code": "validation_error", "message": "...", "details": [...]}
}
```

`details` is `null` when not applicable. Unmatched API URLs also return this
envelope (`404 not_found`) instead of an HTML error page. Stable codes:
`bad_request` (400), `invalid_credentials` (401), `permission_denied` (403),
`not_found` (404), `method_not_allowed` (405), `conflict` (409),
`payload_too_large` (413), `unsupported_media_type` (415), `validation_error`
(422), `internal_error` (500), `service_unavailable` (503). Unexpected failures
are `internal_error`; only transient conditions (for example a locked database)
are `service_unavailable`.

## Format

JSON request and response bodies. Dates are ISO `YYYY-MM-DD`; timestamps are ISO
8601 in UTC with a trailing `Z` (for example `2026-01-05T09:00:00Z`). All numeric
values are JSON numbers and missing values are JSON `null` (never `0`).

## Validation guardrails

- Integer fields reject floats, booleans and non-integer strings (so `limit=50.5`
  and `limit=true` are `422`). Boolean fields accept only the literal strings
  `true` and `false` (so `weighted=1` is `422`). Date fields must be valid
  `YYYY-MM-DD` values. Unknown query parameters, repeated query parameters,
  invalid enum values and unparseable values are `422` — including on routes that
  declare no filters: passing any query parameter to a reference, identity,
  yearly-totals, records or session-detail route is `422`. No value is silently
  coerced to zero or clamped.
- `start <= end` is required and a span of more than 1830 days (about five years)
  is `422`. `limit` must be between 1 and 200; `limit > 200` is `422`, not
  clamped. `offset >= 0`. Aggregated endpoints return summaries; raw sets are
  opt-in via the raw endpoints.
- Where a date range is omitted, the effective range is the span of the owner's
  data within that endpoint's other filters, or empty when there is no data.

## Collections

Paginated responses carry `items`, the complete filtered `count`,
`next`/`previous` continuation paths (relative URLs that preserve all other query
parameters) and `has_more`. The default `limit` is 50. `sort` accepts a documented
key, optionally prefixed with `-` for descending order, and always appends `id`
ascending as a unique tiebreaker.

## Summary

`GET /summary` returns:

| Field | Type | Definition |
| --- | --- | --- |
| `sessions` | int | Matching sessions |
| `sets` | int | Sum of matching sessions' `set_count` |
| `volume_kg` | number | Sum of matching sessions' `total_volume_kg` |
| `volume_t` | number | `volume_kg / 1000` |
| `hours` | number | Sum of `duration_min` (null counts as 0) divided by 60 |
| `sessions_per_week` | number | `sessions / weeks`, where `weeks = max(effective_span_days + 1, 1) / 7` |
| `avg_volume_per_session` | number | `volume_kg / sessions`, or 0 when there are none |
| `avg_session_min` | number | total `duration_min` / sessions, or 0 |
| `days_since_last_session` | int or null | `(today - latest session_date).days`, null when there are none |

All derived numbers are rounded to two decimals.

## Time series

`bucket` starts on the day, the Monday of the ISO week, the 1st of the month or
the 1st of the year. Every bucket between the effective start and end is present
(zero-filled). When both `start` and `end` are supplied, the whole interval is
zero-filled even if no sessions match it.

- `sessions` counts sessions; `volume` sums set `volume_kg`; `training-time` sums
  session `duration_min / 60`; `volume-per-session` is bucket volume / bucket
  session count (0 if none).
- `moving_average=true` is valid only with `bucket=week` (otherwise `422`) and
  adds `value_4wma`: the mean of the current and previous three bucket values, or
  `null` for the first three buckets. It applies to the series `value`, not to
  group values.
- `groups` is `null` without `group_by`, otherwise an array of `{key, value}`
  covering every group seen in the series (missing buckets are 0).

`group_by` matrix (`-` means `422`):

| Endpoint | `program` | `muscle` | `exercise` |
| --- | --- | --- | --- |
| `/series/sessions` | sessions per program | - | - |
| `/series/volume` | volume per program | volume per muscle group | volume per exercise |
| `/series/volume-per-session` | volume / sessions per program | - | - |
| `/series/training-time` | hours per program | - | - |

Group values for `volume` come from set `volume_kg`; the muscle group of a set is
its exercise's `exercise_meta.muscle_group`, falling back to `Other`.

## Breakdowns

`count` is the number of rows before `limit` is applied, so a truncated breakdown
is detectable; `items` holds at most `limit` rows. Weekday rows are in
Monday-to-Sunday order; all other breakdowns are sorted by `volume_kg` descending
then `key` ascending.

- `weekday`: one row per weekday name, Monday first. Sessions are counted by
  `session_date`'s weekday; `sets` and `volume_kg` come from those sessions.
- `program`: one row per program; `sets` and `volume_kg` come from those sessions.
- `muscle` / `exercises`: `sessions` is the number of distinct sessions with at
  least one matching set, `sets` the number of matching sets and `volume_kg` their
  summed volume.

All numbers are rounded to two decimals.

## Exercise endpoints

Exercise names may contain `/`; percent-encode it in the path and the route still
resolves the full name.

- `progress` groups by `session_date`, sorted by date ascending.
  `best_est_1rm_kg` and `top_weight_kg` are `null` when the day has no weighted
  sets. No 12-rep cap is applied.
- `records` returns one row per distinct rep count, sorted by `reps` ascending.
  The row is the best set for that rep count, tie-broken by highest weight, then
  highest `est_1rm_kg`, then most recent `set_time`.
- `sets` is a paginated collection of set records (see Raw).

## Records

- `est-1rm`: one row per exercise with a non-null `est_1rm_kg`, sorted by
  `est_1rm_kg` descending. Tie-breaks: higher reps, then higher weight, then more
  recent `set_time`. No 12-rep cap.
- `bodyweight`: one row per exercise with at least one bodyweight (weight null)
  set, sorted by `reps` descending. The row is the set with the most reps,
  tie-broken by most recent `set_time`.

## Yearly

- `yearly` returns one row per year with data, sorted by year ascending. Numbers
  are rounded to two decimals.
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
and the projection all use that same cutoff (clamped for leap days), so an
`as_of` from another year never compares a full year against a partial one.
`elapsed_days` includes the cutoff; `days_in_year` is 365 or 366;
`remaining_weeks = (days_in_year - elapsed_days) / 7`. Projections and weekly
needs are computed from unrounded totals; all numbers in the response are rounded
to two decimals.

## Raw endpoints

With `weighted=true`, a session qualifies if it has at least one weighted set;
with `weighted=false`, only sessions whose sets are all bodyweight qualify.

`set_time` is the earliest set time in the session for session rows; session
`set_count` and `total_volume_kg` are stored at import time. `rpe` is nullable in
6.0–10.0 and never feeds any aggregate.
