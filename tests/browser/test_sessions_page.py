import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from workouts.models import ApiToken, ExerciseMeta, WorkoutSession, WorkoutSet
from workouts.services import import_workouts_csv

HEADER = "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"

GROUPED_CSV = HEADER + (
    "2026-01-05 09:00:00,Axlar, 54m,Bench Press (Barbell),1,80,5,0,0,8\n"
    "2026-01-05 09:02:00,Axlar, 54m,Bench Press (Barbell),2,82.5,5,0,0,8\n"
    "2026-01-05 09:05:00,Axlar, 54m,Incline Bench (Barbell),1,60,8,0,0,8\n"
    "2026-01-05 09:07:00,Axlar, 54m,Bench Press (Barbell),3,75,6,0,0,7\n"
)


@pytest.fixture(autouse=True)
def pending_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("STRONG_PENDING_DIR", str(tmp_path / "pending"))


def session_with_data(username="alice", csv_text=GROUPED_CSV):
    user = get_user_model().objects.create_user(username=username, password="x")
    import_workouts_csv(user, csv_text)
    return user


@pytest.mark.django_db
def test_sets_are_grouped_per_exercise_in_first_seen_order(client):
    user = session_with_data()
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    bench = content.index("Bench Press (Barbell)")
    incline = content.index("Incline Bench (Barbell)")
    assert bench < incline
    assert content.count('class="set-group"') == 2
    assert (
        'Bench Press (Barbell)\n            <span class="set-group-count">3 sets</span>' in content
    )


@pytest.mark.django_db
def test_set_numbers_restart_for_each_exercise(client):
    user = session_with_data()
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert content.count('<td class="num">1</td>') == 2
    assert content.count('<td class="num">3</td>') == 1


@pytest.mark.django_db
def test_grouped_table_has_a_caption_and_column_scopes(client):
    user = session_with_data()
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert 'scope="rowgroup"' in content
    assert 'class="visually-hidden">Axlar on 2026-01-05: 4 sets</caption>' in content


@pytest.mark.django_db
def test_program_is_hidden_when_it_matches_the_workout_name(client):
    user = session_with_data(
        csv_text=HEADER + "2026-01-05 09:00:00,Push Day,54m,Bench Press,1,80,5,0,0,8\n"
    )
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert "Push Day" in content
    assert "Program Push Day" not in content


@pytest.mark.django_db
def test_program_is_shown_when_it_differs_from_the_workout_name(client):
    user = session_with_data(
        csv_text=HEADER + "2026-01-05 09:00:00,Push Day #2,54m,Bench Press,1,80,5,0,0,8\n"
    )
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert "Push Day #2" in content
    assert "Program Push Day" in content


@pytest.mark.django_db
def test_empty_state_is_not_repeated(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert content.count("No sessions yet.") == 1
    assert content.count("Upload a Strong CSV export to see your workouts here.") == 1


@pytest.mark.django_db
def test_delete_link_only_appears_with_sessions(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)
    assert reverse("delete_sessions") not in client.get(reverse("sessions")).content.decode()

    import_workouts_csv(user, GROUPED_CSV)
    content = client.get(reverse("sessions")).content.decode()

    assert reverse("delete_sessions") in content
    assert "Delete all sessions" in content


@pytest.mark.django_db
def test_delete_removes_sessions_and_sets_but_keeps_corrections_and_tokens(client):
    user = session_with_data()
    client.force_login(user)
    ExerciseMeta.objects.filter(owner=user).update(muscle_group="Chest")
    token = ApiToken.objects.create(owner=user, name="laptop", key_hash="a" * 64, prefix="abcdefgh")

    response = client.post(reverse("delete_sessions"))

    assert response.status_code == 302
    assert response.url == reverse("sessions")
    assert not WorkoutSession.objects.filter(owner=user).exists()
    assert not WorkoutSet.objects.filter(owner=user).exists()
    assert set(ExerciseMeta.objects.filter(owner=user).values_list("muscle_group", flat=True)) == {
        "Chest"
    }
    assert ApiToken.objects.filter(pk=token.pk).exists()


@pytest.mark.django_db
def test_delete_is_owner_scoped(client):
    alice = session_with_data("alice")
    bob = session_with_data("bob")
    client.force_login(alice)

    client.post(reverse("delete_sessions"))

    assert not WorkoutSession.objects.filter(owner=alice).exists()
    assert WorkoutSession.objects.filter(owner=bob).exists()


@pytest.mark.django_db
def test_delete_rejects_get(client):
    user = session_with_data()
    client.force_login(user)

    response = client.get(reverse("delete_sessions"))

    assert response.status_code == 405
    assert WorkoutSession.objects.filter(owner=user).exists()


@pytest.mark.django_db
def test_delete_reports_what_it_removed(client):
    user = session_with_data()
    client.force_login(user)

    content = client.post(reverse("delete_sessions"), follow=True).content.decode()

    assert "Deleted 1 session and 4 sets." in content


@pytest.mark.django_db
def test_delete_confirm_state_is_rendered_without_javascript(client):
    user = session_with_data()
    client.force_login(user)

    initial = client.get(reverse("sessions")).content.decode()
    assert 'href="?delete=1"' in initial
    assert "Really delete 1 session" in initial
    assert " hidden data-delete-form>" in initial

    confirming = client.get(reverse("sessions"), {"delete": "1"}).content.decode()
    assert 'href="?delete=1"' not in confirming
    assert " hidden data-delete-form>" not in confirming


@pytest.mark.django_db
def test_delete_link_ignores_active_filters_when_reporting_the_total(client):
    user = session_with_data()
    client.force_login(user)

    content = client.get(reverse("sessions"), {"q": "nothing-matches"}).content.decode()

    assert "Removes all 1 session" in content


@pytest.mark.django_db
def test_disabled_pager_link_has_no_target_to_activate(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    rows = "\n".join(
        f"2026-01-{day:02d} 09:00:00,Push Day,54m,Bench Press,1,80,5,0,0,8" for day in range(1, 27)
    )
    import_workouts_csv(user, HEADER + rows + "\n")
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    pager = content.split('class="pager"')[1].split("</nav>")[0]
    disabled = [segment for segment in pager.split("<a ")[1:] if 'aria-disabled="true"' in segment]
    assert len(disabled) == 1
    assert "href=" not in disabled[0]
    assert 'tabindex="0"' in disabled[0]
