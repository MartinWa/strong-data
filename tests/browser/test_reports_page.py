import re
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from workouts.reports import build_report
from workouts.services import import_workouts_csv

HEADER = "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"


def row(day, workout, duration, exercise, order, weight, reps):
    weight_text = "" if weight is None else str(weight)
    return f"{day} 09:00:00,{workout},{duration},{exercise},{order},{weight_text},{reps},0,0,8\n"


def report_csv(today):
    rows = [
        row(today, "Push Day #1", "54m", "Bench Press (Barbell)", 1, 80, 5),
        row(today, "Push Day #1", "54m", "Pull Up", 2, None, 8),
        row(today - timedelta(days=1), "Pull Day #2", "1h 2m", "Seated Row (Cable)", 1, 60, 10),
        row(today - timedelta(days=1), "Pull Day #2", "1h 2m", "Pull Up", 2, None, 10),
        row(today - timedelta(days=3), "Push Day #2", "45m", "Bench Press (Barbell)", 1, 85, 5),
        row(today - timedelta(days=3), "Push Day #2", "45m", "Squat (Barbell)", 2, 100, 5),
        row(today - timedelta(days=30), "Push Day #3", "50m", "Bench Press (Barbell)", 1, 75, 5),
        row(today - timedelta(days=60), "Pull Day #1", "40m", "Seated Row (Cable)", 1, 60, 8),
        row(date(today.year - 1, 6, 1), "Push Day", "40m", "Bench Press (Barbell)", 1, 70, 5),
        row(date(today.year - 2, 6, 1), "Push Day", "40m", "Bench Press (Barbell)", 1, 65, 5),
        row(date(today.year - 2, 6, 2), "Legacy", "30m", "Squat (Barbell)", 1, 80, 5),
    ]
    return HEADER + "".join(rows)


@pytest.fixture
def report_user(db):
    user = get_user_model().objects.create_user(username="report-user", password="x")
    import_workouts_csv(user, report_csv(timezone.localdate()))
    return user


@pytest.fixture
def signed_in(client, report_user):
    client.force_login(report_user)
    return client


def test_reports_requires_login(client):
    response = client.get(reverse("reports"))
    assert response.status_code == 302
    assert reverse("login") in response["Location"]


def test_nav_marks_reports_active_on_both_routes(signed_in):
    content = signed_in.get(reverse("reports")).content.decode()
    assert 'href="/reports/" class="active" aria-current="page"' in content

    drill = signed_in.get(reverse("report_exercise", kwargs={"name": "Bench Press (Barbell)"}))
    assert drill.status_code == 200
    assert 'href="/reports/" class="active" aria-current="page"' in drill.content.decode()


def test_default_state_uses_twelve_weeks_and_volume(signed_in):
    response = signed_in.get(reverse("reports"))
    assert response.status_code == 200
    content = response.content.decode()
    assert response.context["range_key"] == "12w"
    assert response.context["metric"] == "volume"
    assert 'name="range" value="12w"' in content
    assert 'name="metric" value="volume"' in content
    assert (
        'class="segmented-item is-current" href="?range=12w" aria-current="true">12 weeks'
        in content
    )
    assert (
        'class="segmented-item is-current" href="?metric=volume" aria-current="true">Volume'
        in content
    )


def test_range_and_metric_links_keep_the_other_parameters(signed_in):
    content = signed_in.get(
        reverse("reports") + "?range=1y&metric=time&program=Push%20Day&year=2025"
    ).content.decode()
    assert 'href="?range=4w&amp;metric=time&amp;program=Push+Day&amp;year=2025"' in content
    assert 'name="range" value="1y"' in content
    assert 'name="metric" value="time"' in content
    assert 'name="year" value="2025"' in content
    assert 'value="Push Day" selected' in content
    assert 'type="submit">Apply' in content


def test_program_filter_changes_the_page_and_preserves_state(signed_in):
    response = signed_in.get(reverse("reports") + "?range=12w&program=Pull%20Day")
    assert response.status_code == 200
    assert response.context["selected_program"] == "Pull Day"
    assert response.context["summary"]["sessions"] == 2
    assert response.context["range_key"] == "12w"


def test_metric_switch_maps_to_the_series_metric(signed_in):
    response = signed_in.get(reverse("reports") + "?metric=time")
    assert response.context["training_load"]["metric"] == "time"
    assert response.context["training_load"]["chart"]["aria_label"].startswith("Hours per week")
    assert 'name="metric" value="time"' in response.content.decode()


def test_kpis_and_previous_window_deltas(signed_in):
    response = signed_in.get(reverse("reports") + "?range=4w")
    context = response.context
    summary = context["summary"]
    assert (summary["sessions"], summary["sets"]) == (3, 6)
    assert summary["volume_kg"] == 1925.0
    assert summary["hours"] == 2.68
    delta = context["kpis"][0]["delta"]
    assert delta["text"] == "↑ 200%"
    assert delta["aria"] == "up 200 percent versus the previous 4 weeks"
    content = response.content.decode()
    assert "1.9 t" in content
    assert "↑ 200%" in content


def test_range_without_sessions_offers_way_back_and_hides_blocks(signed_in):
    content = signed_in.get(reverse("reports") + "?range=4w&program=Legacy").content.decode()
    assert "No sessions in" in content
    assert "Show all time" in content
    assert "Clear program" in content
    assert "report-kpis" not in content
    assert "Training load" not in content


def test_no_sessions_at_all_shows_the_upload_call_to_action(client, db):
    user = get_user_model().objects.create_user(username="empty", password="x")
    client.force_login(user)
    content = client.get(reverse("reports")).content.decode()
    assert "No sessions yet." in content
    assert "Upload CSV export" in content
    assert "report-toolbar" not in content
    assert "<svg" in content


def test_bodyweight_only_range_draws_a_zero_axis_without_nan(client, db):
    user = get_user_model().objects.create_user(username="bodyweight", password="x")
    today = timezone.localdate()
    import_workouts_csv(
        user,
        HEADER + row(today, "Pull", "30m", "Pull Up", 1, None, 10),
    )
    client.force_login(user)
    response = client.get(reverse("reports") + "?range=4w")
    content = response.content.decode()
    assert response.status_code == 200
    assert "No volume in this period." in content
    assert "NaN" not in content
    assert "inf" not in content.lower().replace("in progress", "")


def test_partial_buckets_are_marked_in_the_chart(signed_in):
    content = signed_in.get(reverse("reports") + "?range=12w").content.decode()
    assert "bar-partial" in content
    assert "in progress" in content


def test_svg_charts_are_accessible_and_numeric(signed_in):
    content = signed_in.get(reverse("reports")).content.decode()
    assert 'role="img"' in content
    assert 'aria-label="Volume per week' in content
    assert 'aria-label="Cumulative volume' in content
    for match in re.finditer(r'(?:x|y|width|height|points|dx|dy)="([^"]*)"', content):
        value = match.group(1).lower()
        assert "nan" not in value
        assert "inf" not in value
        assert "none" not in value


def test_heatmap_is_capped_and_aligned(signed_in):
    content = signed_in.get(reverse("reports") + "?range=all").content.decode()
    cells = content.split('class="heatmap-grid"', 1)[1].split("</div>", 1)[0]
    assert cells.count("heat-cell") % 7 == 0
    assert cells.count("heat-cell") // 7 <= 53
    assert "is-outside" in cells
    assert "Mon" in content
    assert "Sun" in content
    assert "Less" in content
    assert "More" in content


def test_heatmap_and_streaks_come_from_distinct_training_dates(signed_in):
    context = signed_in.get(reverse("reports") + "?range=12w").context
    consistency = context["consistency"]
    assert consistency["streaks"]["days"] == 5
    assert consistency["streaks"]["longest"] == 2
    assert consistency["streaks"]["current"] == 2
    assert all(len(week["cells"]) == 7 for week in consistency["weeks"])
    assert len(consistency["heat_rows"]) == 5


def test_weekday_bars_accent_the_busiest_day_and_have_a_table(signed_in):
    response = signed_in.get(reverse("reports") + "?range=12w")
    context_weekdays = response.context["consistency"]["weekdays"]
    assert len(context_weekdays) == 7
    assert context_weekdays[0]["key"] == "Mon"
    busiest = max(row["sessions"] for row in context_weekdays)
    assert any(row["accent"] for row in context_weekdays) is (busiest > 0)
    content = response.content.decode()
    assert "is-busiest" in content
    assert "Weekday numbers" in content
    assert "Sessions, sets and volume per weekday" in content


def test_muscle_rows_are_not_links(signed_in):
    content = signed_in.get(reverse("reports")).content.decode()
    section = content.split('class="muscle-bars"', 1)[1].split("</ul>", 1)[0]
    assert "<a " not in section
    assert "Share of sets" in content
    assert "%" in section


def test_records_show_prs_first_records_and_drill_down_links(signed_in):
    content = signed_in.get(reverse("reports") + "?range=12w").content.decode()
    assert "NEW PR" in content
    assert "First recorded" in content
    assert 'href="/reports/exercise/Bench%20Press%20(Barbell)/"' in content
    assert "Bench Press (Barbell)" in content
    assert "100 kg × 5" in content


def test_record_links_round_trip_awkward_names(client, db):
    user = get_user_model().objects.create_user(username="names", password="x")
    today = timezone.localdate()
    names = ["Bench/Press", "A & B", "Overhead (Barbell)"]
    rows = [row(today, "Push", "30m", name, 1, 60, 5) for name in names]
    import_workouts_csv(user, HEADER + "".join(rows))
    client.force_login(user)

    for name in names:
        response = client.get(reverse("report_exercise", kwargs={"name": name}))
        assert response.status_code == 200, name
        assert escape(name) in response.content.decode()


def test_ten_year_history_renders_the_all_chart(client, db):
    user = get_user_model().objects.create_user(username="long", password="x")
    today = timezone.localdate()
    rows = [
        row(today.replace(year=today.year - 10), "Old", "30m", "Bench Press (Barbell)", 1, 60, 5),
        row(today, "Recent", "30m", "Bench Press (Barbell)", 1, 90, 5),
    ]
    import_workouts_csv(user, HEADER + "".join(rows))
    client.force_login(user)

    response = client.get(reverse("reports") + "?range=all")
    assert response.status_code == 200
    content = response.content.decode()
    assert "date range may not exceed" not in content
    assert "chart-bar" in content
    assert response.context["summary"]["sessions"] == 2


def test_data_tables_and_print_attributes(signed_in):
    content = signed_in.get(reverse("reports")).content.decode()
    assert "Show the numbers" in content
    assert "Yearly totals" in content
    assert "Cumulative volume by month" in content
    assert "data-print-open" in content
    assert "workouts/print.js" in content


def test_yearly_current_year_footer_and_past_year_footer(signed_in):
    current = signed_in.get(reverse("reports")).context["yearly"]
    assert current["focus"] == timezone.localdate().year
    assert current["footer"]["kind"] == "current"
    assert current["footer"]["can_project"] is False or current["footer"]["projected"]

    previous_year = timezone.localdate().year - 1
    response = signed_in.get(reverse("reports") + f"?year={previous_year}")
    past = response.context["yearly"]
    assert past["focus"] == previous_year
    assert past["footer"]["kind"] == "past"
    assert "projected" not in past["footer"]
    past_content = response.content.decode()
    assert "Projected year end" not in past_content
    assert "Versus the year before" in past_content


def test_invalid_year_falls_back_without_an_error(signed_in):
    response = signed_in.get(reverse("reports") + "?year=1800")
    assert response.status_code == 200
    assert response.context["yearly"]["focus"] == timezone.localdate().year


def test_one_year_of_data_has_no_comparison_legend(client, db):
    user = get_user_model().objects.create_user(username="oneyear", password="x")
    today = timezone.localdate()
    import_workouts_csv(
        user,
        HEADER + row(today, "Push", "30m", "Bench Press (Barbell)", 1, 80, 5),
    )
    client.force_login(user)
    content = client.get(reverse("reports")).content.decode()
    assert "chart-legend" not in content
    assert "Year to date" in content


def test_january_focus_withholds_the_projection(client, db):
    user = get_user_model().objects.create_user(username="january", password="x")
    import_workouts_csv(
        user,
        HEADER + row(date(2026, 1, 5), "Push", "30m", "Bench Press (Barbell)", 1, 80, 5),
    )
    context = build_report(user, {}, date(2026, 1, 10))
    assert context["yearly"]["footer"]["kind"] == "current"
    assert context["yearly"]["footer"]["can_project"] is False
    assert context["yearly"]["footer"]["projected"] is None

    later = build_report(user, {}, date(2026, 2, 15))
    assert later["yearly"]["footer"]["can_project"] is True
    assert later["yearly"]["footer"]["projected"] is not None


def test_yearly_curve_covers_a_past_focus_year_fully(client, db):
    user = get_user_model().objects.create_user(username="past", password="x")
    import_workouts_csv(
        user,
        HEADER
        + row(date(2024, 6, 1), "Push", "30m", "Bench Press (Barbell)", 1, 70, 5)
        + row(date(2025, 6, 1), "Push", "30m", "Bench Press (Barbell)", 1, 80, 5),
    )
    context = build_report(user, {"range": "all", "year": "2024"}, date(2026, 3, 1))
    assert context["yearly"]["focus"] == 2024
    line = context["yearly"]["chart"]["lines"][0]
    assert line["points"].count(",") == 366


def test_query_count_is_bounded(signed_in):
    with CaptureQueriesContext(connection) as captured:
        response = signed_in.get(reverse("reports") + "?range=12w")
    assert response.status_code == 200
    assert len(captured.captured_queries) < 40


def test_report_pages_do_not_fetch_external_assets(signed_in):
    content = signed_in.get(reverse("reports")).content.decode()
    for match in re.findall(r'<script[^>]+src="([^"]+)"', content):
        assert match.startswith("/"), match
    for match in re.findall(r'<link[^>]+href="([^"]+)"', content):
        assert match.startswith("/"), match
