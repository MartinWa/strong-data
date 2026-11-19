from datetime import date, datetime

import pytest

from workouts.templatetags.formatting import isodate, kg, num


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "—"),
        ("", "—"),
        ("nope", "—"),
        (0, "0"),
        ("0.00", "0"),
        (480, "480"),
        ("480.00", "480"),
        ("5977.50", "5,977.5"),
        (1234567, "1,234,567"),
        ("75.00", "75"),
    ],
)
def test_num_trims_and_groups(value, expected):
    assert num(value) == expected


@pytest.mark.parametrize(
    ("value", "places", "expected"),
    [(480, "2", "480.00"), ("5977.50", 0, "5,978")],
)
def test_num_honours_an_explicit_precision(value, places, expected):
    assert num(value, places) == expected


def test_kg_appends_the_unit_and_dashes_missing_values():
    assert kg("480.00") == "480 kg"
    assert kg(None) == "—"


def test_isodate_renders_iso_and_dashes_missing_values():
    assert isodate(date(2026, 1, 5)) == "2026-01-05"
    assert isodate(datetime(2026, 1, 5, 9, 0)) == "2026-01-05 09:00"
    assert isodate(None) == "—"


def test_isodate_can_drop_the_time():
    assert isodate(datetime(2026, 1, 5, 9, 0), "day") == "2026-01-05"
