from datetime import date

import pytest

from api.queries import series_data
from tests.api.conftest import make_user

CSV = (
    "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
    "2026-01-05 09:00:00,Push Day #1,1m,Bench Press,1,40.00,1,0,0,8.0\n"
    "2026-01-05 09:01:00,Push Day #2,2m,Bench Press,1,40.01,1,0,0,8.0\n"
)
START = date(2026, 1, 1)
END = date(2026, 1, 31)
EXPECTED = {
    "volume": 80.01,
    "sessions": 2,
    "training-time": 0.05,
    "volume-per-session": 40.01,
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("metric", "group_by"),
    [
        ("volume", "program"),
        ("volume", "muscle"),
        ("volume", "exercise"),
        ("sessions", "program"),
        ("training-time", "program"),
        ("volume-per-session", "program"),
    ],
)
def test_grouped_series_matches_ungrouped_bucket_totals(metric, group_by):
    user = make_user("series-parity", CSV, "series-parity-secret")
    ungrouped = series_data(user, metric, "week", None, START, END, False, None)
    grouped = series_data(user, metric, "week", group_by, START, END, False, None)

    assert [item["value"] for item in grouped["items"]] == [
        item["value"] for item in ungrouped["items"]
    ]
    bucket = next(item for item in ungrouped["items"] if item["bucket_start"] == "2026-01-05")
    assert bucket["value"] == EXPECTED[metric]
