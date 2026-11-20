# Data model

strong-data stores one SQLite database per installation. Every table is owned by
a user, and every row carries a non-null `owner` foreign key, so a query that
forgets to scope by owner is a bug rather than a leak. The schema is created and
changed only through Django migrations (`workouts/migrations/`); the initial
migration is `0001_initial`.

## Tables

### `workout_session`

One row per workout performed on a date.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigint, PK | |
| `owner` | FK → user | `ON DELETE CASCADE`, related name `sessions` |
| `session_date` | date | Local date of the workout |
| `program` | varchar(255) | Derived: `workout_name` with a trailing ` #N` removed |
| `workout_name` | varchar(255) | Raw name from the export, e.g. `Push Day #1` |
| `start_time` | datetime | Earliest `set_time` in the session, stored UTC |
| `duration_min` | integer, null | Parsed from the export's `Duration` column |
| `set_count` | integer, default 0 | Derived: number of sets in the session |
| `total_volume_kg` | decimal(12,2), default 0 | Derived: sum of the session's `volume_kg` |

Constraints: unique `(owner, session_date, workout_name)`; `set_count >= 0`;
`total_volume_kg >= 0`. Index on `session_date`. Default ordering is
`session_date, workout_name`.

### `workout_set`

One row per set.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigint, PK | |
| `owner` | FK → user | `ON DELETE CASCADE`, related name `sets` |
| `session` | FK → `workout_session` | `ON DELETE CASCADE`, related name `sets` |
| `exercise` | FK → `exercise` | `ON DELETE CASCADE`, related name `sets` |
| `set_order` | integer | Position within the exercise in that session |
| `weight_kg` | decimal(8,2), null | Null for bodyweight sets, including exports that encode bodyweight as `0` |
| `reps` | integer, default 0 | |
| `rpe` | decimal(3,1), null | 6.0–10.0 in 0.5 steps, otherwise null |
| `distance` | decimal(8,2), null | For distance-based sets |
| `seconds` | decimal(8,2), null | For timed sets |
| `set_time` | datetime | Timestamp from the export, read in `STRONG_TIME_ZONE` and stored UTC |
| `volume_kg` | decimal(12,2), default 0 | Derived: `COALESCE(weight_kg, 0) * reps` |
| `est_1rm_kg` | decimal(8,2), null | Derived: Epley estimate, null for bodyweight |

Constraints: `set_order >= 1`; `reps >= 0`; `volume_kg >= 0`. Default ordering is
`set_time, set_order`.

### `exercise`

One row per exercise name the user has imported.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigint, PK | |
| `owner` | FK → user | `ON DELETE CASCADE`, related name `exercises` |
| `name` | varchar(255) | Exercise name as it appears in the export |

Constraint: unique `(owner, name)`. Default ordering is `name`.

### `exercise_meta`

The user's muscle-group mapping, keyed by exercise name rather than by
`exercise` row, so it survives re-imports.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigint, PK | |
| `owner` | FK → user | `ON DELETE CASCADE`, related name `exercise_meta` |
| `exercise_name` | varchar(255) | Matches `exercise.name` |
| `muscle_group` | varchar(64) | Heuristic guess at import, user-correctable |

Constraint: unique `(owner, exercise_name)`. Default ordering is `exercise_name`.

### `api_token`

Bearer tokens for the JSON API. The secret itself is never stored.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigint, PK | |
| `owner` | FK → user | `ON DELETE CASCADE`, related name `api_tokens` |
| `name` | varchar(255) | User-chosen label |
| `key_hash` | varchar(64), unique | SHA-256 hex digest of the secret |
| `prefix` | varchar(16), indexed | First 8 characters, for display and lookup |
| `created_at` | datetime | Set on creation |
| `expires_at` | datetime, null | Enforced by the API when set |
| `revoked_at` | datetime, null | Set when the user revokes the token |

Constraint: unique `(owner, name)`. Default ordering is `-created_at`.

## Derived fields

These are computed once at import time and stored, so API queries stay simple and
portable:

- `program` — `workout_name` with a trailing ` #N` stripped. Sessions are keyed
  by the raw `workout_name`; `program` is only a grouping and filter dimension.
- `volume_kg` — `COALESCE(weight_kg, 0) * reps`.
- `est_1rm_kg` — Epley, `weight_kg * (1 + reps / 30)`, and null when the set has
  no weight or no reps. Strong's UI documents Brzycki instead; Epley is used
  deliberately and `docs/api.md` explains the difference.
- `set_count` and `total_volume_kg` — aggregates over the session's sets.

RPE never feeds `volume_kg`, `est_1rm_kg` or any aggregate.

## Import keying and replacement

Sessions are keyed per owner by `(session_date, workout_name)`. Confirming an
import replaces the owner's sessions, sets and exercise rows in a single
transaction, which makes re-import idempotent. `exercise_meta` is never deleted
by an import, so muscle-group corrections — including corrections for exercises
absent from the new export — survive.

## Ownership and access

- Every table has a non-null `owner` FK, enforced by the schema.
- No user id appears in any URL. The web UI scopes every queryset to
  `request.user`; the API resolves the bearer token to a user and scopes every
  queryset to that user.
- Tokens store only a SHA-256 hash and an 8-character prefix; the secret is shown
  once at creation.

## Migrations

Schema changes are made with `manage.py makemigrations` and committed as
migrations — never by editing the database by hand. CI runs
`manage.py makemigrations --check --dry-run` so a model change without a
migration fails the build, and the container applies migrations automatically on
start.
