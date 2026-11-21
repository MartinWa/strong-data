from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from tests.browser.test_reports_page import HEADER, row
from workouts.services import import_workouts_csv


def make_user(username, csv_text):
    user = get_user_model().objects.create_user(username=username, password="x")
    import_workouts_csv(user, csv_text)
    return user


@pytest.fixture
def weighted_user(db):
    today = timezone.localdate()
    csv_text = HEADER + (
        row(today, "Push Day #1", "54m", "Bench Press (Barbell)", 1, 80, 5)
        + row(today - timedelta(days=7), "Push Day #2", "50m", "Bench Press (Barbell)", 1, 85, 5)
        + row(today - timedelta(days=14), "Pull Day", "40m", "Seated Row (Cable)", 1, 60, 10)
    )
    return make_user("weighted", csv_text)


@pytest.fixture
def bodyweight_user(db):
    today = timezone.localdate()
    csv_text = HEADER + (
        row(today, "Pull Day #1", "40m", "Pull Up", 1, None, 8)
        + row(today - timedelta(days=7), "Pull Day #2", "40m", "Pull Up", 1, None, 12)
    )
    return make_user("bodyweight", csv_text)


def test_unknown_exercise_is_a_404(client, weighted_user):
    client.force_login(weighted_user)
    response = client.get(reverse("report_exercise", kwargs={"name": "Unknown Lift"}))
    assert response.status_code == 404


def test_foreign_exercise_is_a_404(client, weighted_user, db):
    make_user(
        "other",
        HEADER + row(timezone.localdate(), "Secret", "30m", "Secret Lift", 1, 50, 5),
    )
    client.force_login(weighted_user)
    response = client.get(reverse("report_exercise", kwargs={"name": "Secret Lift"}))
    assert response.status_code == 404


def test_weighted_exercise_plots_estimated_1rm(client, weighted_user):
    client.force_login(weighted_user)
    response = client.get(reverse("report_exercise", kwargs={"name": "Bench Press (Barbell)"}))
    assert response.status_code == 200
    content = response.content.decode()
    assert response.context["metric_label"] == "Estimated 1RM"
    assert "Estimated 1RM" in content
    assert 'role="img"' in content
    assert "kg" in response.context["chart"]["ticks"][-1]["label"]
    assert "NaN" not in content
    assert "None" not in content


def test_bodyweight_exercise_falls_back_to_max_reps(client, bodyweight_user):
    client.force_login(bodyweight_user)
    response = client.get(reverse("report_exercise", kwargs={"name": "Pull Up"}))
    assert response.status_code == 200
    assert response.context["metric_label"] == "Max reps"
    assert response.context["chart"]["ticks"][-1]["label"].endswith("reps")
    content = response.content.decode()
    assert "No weighted sets" not in content
    assert "Pull Up" in content


def test_range_and_program_carry_over_with_an_accessible_state(client, weighted_user):
    client.force_login(weighted_user)
    response = client.get(
        reverse("report_exercise", kwargs={"name": "Bench Press (Barbell)"})
        + "?range=all&program=Push%20Day"
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert response.context["range_key"] == "all"
    assert response.context["selected_program"] == "Push Day"
    assert (
        'class="segmented-item is-current" '
        'href="?range=all&amp;program=Push+Day" aria-current="true">All time'
    ) in content
    assert 'name="range" value="all"' in content
    assert 'value="Push Day" selected' in content
    assert 'type="submit">Apply' in content


def test_per_session_table_sits_beside_the_line_chart(client, weighted_user):
    client.force_login(weighted_user)
    content = client.get(
        reverse("report_exercise", kwargs={"name": "Bench Press (Barbell)"}) + "?range=all"
    ).content.decode()
    assert "Show the numbers" in content
    assert "Best set per session for Bench Press (Barbell)" in content
    assert "data-print-open" in content
    assert content.count("polyline") >= 1


def test_records_table_explains_what_the_time_column_means(client, weighted_user):
    client.force_login(weighted_user)
    content = client.get(
        reverse("report_exercise", kwargs={"name": "Bench Press (Barbell)"}) + "?range=all"
    ).content.decode()
    assert "Records by reps" in content
    assert "best set at each rep count" in content
    assert "Set time" in content


def test_exercise_with_no_sets_in_range_shows_a_message_not_a_404(client, weighted_user):
    client.force_login(weighted_user)
    response = client.get(
        reverse("report_exercise", kwargs={"name": "Seated Row (Cable)"})
        + "?range=4w&program=Push%20Day"
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert "No sets for Seated Row (Cable) in" in content
    assert "Records by reps" in content


def test_report_links_lead_to_the_drill_down(client, weighted_user):
    client.force_login(weighted_user)
    content = client.get(reverse("reports") + "?range=all").content.decode()
    assert (
        'href="/reports/exercise/Bench%20Press%20(Barbell)/?range=all&amp;metric=volume"' in content
    )
    response = client.get("/reports/exercise/Bench%20Press%20(Barbell)/?range=all")
    assert response.status_code == 200


def test_drill_down_preserves_filters_in_both_directions(client, weighted_user):
    client.force_login(weighted_user)
    response = client.get(reverse("reports") + "?range=all&metric=time&program=Push%20Day")
    links = [item["url"] for item in response.context["best_lifts"]["strength"]["items"]]
    assert links

    drill = client.get(links[0])
    assert drill.status_code == 200
    assert drill.context["range_key"] == "all"
    assert drill.context["selected_program"] == "Push Day"
    assert "range=all" in drill.context["reports_url"]
    assert "metric=time" in drill.context["reports_url"]
    assert "program=Push+Day" in drill.context["reports_url"]
    content = drill.content.decode()
    assert 'href="/reports/?range=all&amp;metric=time&amp;program=Push+Day"' in content
    assert 'name="metric" value="time"' in content

    back = client.get(drill.context["reports_url"])
    assert back.context["range_key"] == "all"
    assert back.context["metric"] == "time"
    assert back.context["selected_program"] == "Push Day"


def test_single_session_chart_draws_a_marker(client, db):
    today = timezone.localdate()
    user = make_user(
        "single",
        HEADER + row(today, "Push", "30m", "Bench Press (Barbell)", 1, 80, 5),
    )
    client.force_login(user)

    response = client.get(
        reverse("report_exercise", kwargs={"name": "Bench Press (Barbell)"}) + "?range=4w"
    )
    assert response.status_code == 200
    assert response.context["chart"]["lines"][0]["dots"]
    content = response.content.decode()
    assert "chart-dot" in content
    assert "<circle" in content
