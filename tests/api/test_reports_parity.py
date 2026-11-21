from datetime import date
from urllib.parse import urlencode

import pytest

from api.queries import muscle_totals, personal_best_data, yearly_data
from workouts.reports import build_report, series_for_range

BASE = "/api/v1"
TODAY = date(2026, 2, 10)
RANGES = ("4w", "12w", "6m", "1y")
PROGRAMS = (None, "Push Day")


def query(values):
    clean = {key: value for key, value in values.items() if value is not None}
    return urlencode(clean)


def report_context(user, range_key, program):
    params = {"range": range_key}
    if program:
        params["program"] = program
    return build_report(user, params, TODAY)


@pytest.mark.parametrize("range_key", RANGES)
@pytest.mark.parametrize("program", PROGRAMS)
def test_summary_parity(auth, alice, range_key, program):
    context = report_context(alice, range_key, program)
    assert context.get("range_empty") is False
    resolved = context["range"]
    body = auth.get(
        BASE
        + "/summary?"
        + query({"start": resolved["start"], "end": resolved["end"], "program": program})
    ).json()
    for key in (
        "sessions",
        "sets",
        "volume_kg",
        "volume_t",
        "hours",
        "sessions_per_week",
        "avg_volume_per_session",
        "avg_session_min",
    ):
        assert body[key] == context["summary"][key], (range_key, program, key)


@pytest.mark.parametrize("range_key", RANGES)
@pytest.mark.parametrize("program", PROGRAMS)
def test_series_parity(auth, alice, range_key, program):
    context = report_context(alice, range_key, program)
    resolved = context["range"]
    for metric, series_metric in (
        ("volume", "volume"),
        ("sessions", "sessions"),
        ("time", "training-time"),
    ):
        series = series_for_range(
            alice,
            series_metric,
            resolved["bucket"],
            resolved["start"],
            resolved["end"],
            False,
            program,
        )
        body = auth.get(
            BASE
            + f"/series/{series_metric}?"
            + query(
                {
                    "bucket": resolved["bucket"],
                    "start": resolved["start"],
                    "end": resolved["end"],
                    "program": program,
                }
            )
        ).json()
        normalized = [{**item, "value_4wma": item.get("value_4wma")} for item in series["items"]]
        assert body["items"] == normalized, (range_key, program, metric)


@pytest.mark.parametrize("range_key", RANGES)
@pytest.mark.parametrize("program", PROGRAMS)
def test_muscle_parity(auth, alice, range_key, program):
    context = report_context(alice, range_key, program)
    resolved = context["range"]
    rows = muscle_totals(alice, resolved["start"], resolved["end"], program)
    body = auth.get(
        BASE
        + "/breakdown/muscle?"
        + query(
            {
                "start": resolved["start"],
                "end": resolved["end"],
                "program": program,
                "limit": 1000,
            }
        )
    ).json()
    assert body["count"] == len(rows)
    assert body["items"] == rows


@pytest.mark.parametrize("range_key", RANGES)
@pytest.mark.parametrize("program", PROGRAMS)
def test_personal_best_parity(auth, alice, range_key, program):
    context = report_context(alice, range_key, program)
    resolved = context["range"]
    rows = personal_best_data(alice, resolved["start"], resolved["end"], program)
    body = auth.get(
        BASE
        + "/records/personal-bests?"
        + query(
            {
                "start": resolved["start"],
                "end": resolved["end"],
                "program": program,
            }
        )
    ).json()
    assert body["items"] == rows["items"]


def test_yearly_parity(auth, alice):
    context = build_report(alice, {"range": "12w"}, TODAY)
    body = auth.get(BASE + "/yearly").json()
    by_year = {row["year"]: row for row in body["items"]}
    for row in context["yearly"]["totals_rows"]:
        expected = by_year[row["year"]]
        assert row["sessions"] == expected["sessions"]
        assert row["sets"] == expected["sets"]
        assert row["volume"] == f"{expected['volume_t']:.1f} t"
        assert row["hours"] == f"{expected['hours']:.1f} h"


def test_all_range_uses_the_same_numbers_as_dateless_endpoints(auth, alice):
    context = build_report(alice, {"range": "all"}, TODAY)
    resolved = context["range"]
    assert resolved["start"] == date(2026, 1, 1)

    summary = auth.get(BASE + "/summary").json()
    assert summary["sessions"] == context["summary"]["sessions"]
    assert summary["sets"] == context["summary"]["sets"]
    assert summary["volume_kg"] == context["summary"]["volume_kg"]
    assert summary["hours"] == context["summary"]["hours"]

    rows = muscle_totals(alice, resolved["start"], resolved["end"], None)
    muscle = auth.get(BASE + "/breakdown/muscle?limit=1000").json()
    assert muscle["items"] == rows

    records = personal_best_data(alice, resolved["start"], resolved["end"], None)
    bests = auth.get(BASE + "/records/personal-bests?start=2026-01-01").json()
    assert bests["items"] == records["items"]

    assert auth.get(BASE + "/yearly").json()["items"] == yearly_data(alice, None)["items"]
