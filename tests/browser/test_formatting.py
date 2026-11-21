from datetime import UTC, date, datetime

import pytest
from django.core.paginator import Paginator
from django.template import Context, Template
from django.test import override_settings

from workouts.templatetags.formatting import elided_pages, isodate, isominute, kg, num


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


def test_isominute_drops_seconds_from_datetimes_and_strings():
    assert isominute(datetime(2026, 1, 5, 9, 0, 30)) == "2026-01-05 09:00"
    assert isominute("2026-01-05 09:00:30") == "2026-01-05 09:00"
    assert isominute("2026-01-05") == "2026-01-05 00:00"
    assert isominute(None) == "—"


@override_settings(TIME_ZONE="Europe/Stockholm")
@pytest.mark.parametrize("name", ["isodate", "isominute"])
def test_datetime_filters_render_in_the_configured_time_zone(name):
    moment = datetime(2026, 6, 20, 8, 0, tzinfo=UTC)

    rendered = Template(f"{{% load formatting %}}{{{{ value|{name} }}}}").render(
        Context({"value": moment})
    )

    assert rendered == "2026-06-20 10:00"


def test_elided_pages_window_around_the_current_page():
    page = Paginator(list(range(500)), 25).get_page(10)

    assert list(elided_pages(page)) == [1, "…", 9, 10, 11, "…", 20]


def test_elided_pages_do_not_repeat_the_ends():
    page = Paginator(list(range(150)), 25).get_page(1)

    assert list(elided_pages(page)) == [1, 2, "…", 6]


def test_elided_pages_lists_every_page_when_the_list_is_short():
    page = Paginator(list(range(75)), 25).get_page(2)

    assert list(elided_pages(page)) == [1, 2, 3]
