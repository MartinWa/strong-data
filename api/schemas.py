from ninja import Schema


class Envelope(Schema):
    contract_version: str
    generated_at: str


class ErrorBody(Schema):
    code: str
    message: str
    details: list | None


class ErrorOut(Envelope):
    error: ErrorBody


class HealthOut(Envelope):
    status: str


class MeOut(Envelope):
    id: int
    username: str


class ValuesOut(Envelope):
    items: list[str]
    count: int


class SummaryOut(Envelope):
    sessions: int
    sets: int
    volume_kg: float
    volume_t: float
    hours: float
    sessions_per_week: float
    avg_volume_per_session: float
    avg_session_min: float
    days_since_last_session: int | None


class GroupValue(Schema):
    key: str
    value: float


class SeriesItem(Schema):
    bucket_start: str
    value: float
    groups: list[GroupValue] | None
    value_4wma: float | None = None


class SeriesOut(Envelope):
    bucket: str
    group_by: str | None
    count: int
    items: list[SeriesItem]


class BreakdownItem(Schema):
    key: str
    sessions: int
    sets: int
    volume_kg: float


class BreakdownOut(Envelope):
    count: int
    items: list[BreakdownItem]


class ProgressItem(Schema):
    date: str
    session_id: int | None = None
    sets: int
    best_est_1rm_kg: float | None
    top_weight_kg: float | None
    max_reps: int
    volume_kg: float


class ProgressOut(Envelope):
    count: int
    items: list[ProgressItem]


class ExerciseRecordItem(Schema):
    reps: int
    set_count: int
    top_weight_kg: float | None
    best_est_1rm_kg: float | None
    volume_kg: float
    set_time: str


class ExerciseRecordOut(Envelope):
    count: int
    items: list[ExerciseRecordItem]


class Est1rmRecordItem(Schema):
    exercise: str
    est_1rm_kg: float
    reps: int
    weight_kg: float
    set_time: str


class BodyweightRecordItem(Schema):
    exercise: str
    reps: int
    set_time: str
    seconds: float | None
    distance: float | None


class Est1rmRecordOut(Envelope):
    count: int
    items: list[Est1rmRecordItem]


class PersonalBestItem(Schema):
    exercise: str
    kind: str
    value: float
    previous_value: float | None
    improvement: float | None
    is_personal_best: bool
    reps: int
    weight_kg: float | None
    set_time: str


class PersonalBestOut(Envelope):
    count: int
    items: list[PersonalBestItem]


class BodyweightRecordOut(Envelope):
    count: int
    items: list[BodyweightRecordItem]


class YearlyItem(Schema):
    year: int
    sessions: int
    sets: int
    volume_kg: float
    volume_t: float
    hours: float


class YearlyOut(Envelope):
    count: int
    items: list[YearlyItem]


class PaceTotals(Schema):
    sessions: int
    sets: int
    volume_kg: float
    hours: float


class PaceProjection(Schema):
    sessions: float
    sets: float
    volume_kg: float
    hours: float


class PaceNeeded(Schema):
    sessions: float
    sets: float
    volume_kg: float
    hours: float


class PaceRow(Schema):
    year: int
    sessions: int
    volume_kg: float
    cumulative_sessions: int
    cumulative_volume_kg: float


class PaceCurveRow(Schema):
    year: int
    date: str
    day_of_year: int
    sessions: int
    cumulative_sessions: int
    cumulative_volume_kg: float


class PaceOut(Envelope):
    year: int
    ytd: PaceTotals
    last_year_to_date: PaceTotals
    projected: PaceProjection
    needed_per_week: PaceNeeded
    pace: list[PaceRow]


class CurveOut(Envelope):
    year: int
    years: list[int]
    count: int
    items: list[PaceCurveRow]


class SetItem(Schema):
    id: int
    session_id: int
    session_date: str
    exercise: str
    muscle_group: str
    set_order: int
    weight_kg: float | None
    reps: int
    rpe: float | None
    distance: float | None
    seconds: float | None
    set_time: str
    volume_kg: float
    est_1rm_kg: float | None


class SessionItem(Schema):
    id: int
    session_date: str
    program: str
    workout_name: str
    start_time: str
    duration_min: int | None
    set_count: int
    total_volume_kg: float


class SessionDetailOut(Envelope):
    id: int
    session_date: str
    program: str
    workout_name: str
    start_time: str
    duration_min: int | None
    set_count: int
    total_volume_kg: float
    sets: list[SetItem]


class SessionPage(Envelope):
    items: list[SessionItem]
    count: int
    next: str | None
    previous: str | None
    has_more: bool


class SetPage(Envelope):
    items: list[SetItem]
    count: int
    next: str | None
    previous: str | None
    has_more: bool
