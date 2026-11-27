from datetime import date, timedelta
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse

from workouts import pending
from workouts.models import ApiToken, Exercise, ExerciseMeta, WorkoutSession, WorkoutSet
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
def test_empty_state_states_the_state_once_and_leaves_the_action_to_the_button(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert content.count("No sessions yet.") == 1
    assert content.count("Your imported workouts appear here, newest first.") == 1
    assert "Upload a Strong CSV export" not in content
    assert content.count(">Upload CSV export<") == 1


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
    assert not Exercise.objects.filter(owner=user).exists()
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
    assert not Exercise.objects.filter(owner=alice).exists()
    assert Exercise.objects.filter(owner=bob).exists()


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


@pytest.mark.django_db
def test_pager_numbers_the_pages_and_marks_the_current_one(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    rows = "\n".join(
        f"{date(2026, 1, 1) + timedelta(days=day)} 09:00:00,Push Day,54m,Bench Press,1,80,5,0,0,8"
        for day in range(60)
    )
    import_workouts_csv(user, HEADER + rows + "\n")
    client.force_login(user)

    content = client.get(reverse("sessions"), {"page": 2}).content.decode()

    assert '<span class="pager-page is-current" aria-current="page">2</span>' in content
    assert '<a class="pager-page" href="?page=1" aria-label="Page 1">1</a>' in content
    assert '<a class="pager-page" href="?page=3" aria-label="Page 3">3</a>' in content


@pytest.mark.django_db
def test_printing_expands_every_session_and_loads_the_print_script(client):
    user = session_with_data()
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert 'src="/static/workouts/print.js"' in content
    assert content.count("data-print-open") == 1


def test_the_print_script_opens_details_for_paper_and_restores_them():
    script = Path(finders.find("workouts/print.js")).read_text(encoding="utf-8")

    assert '"beforeprint"' in script
    assert '"afterprint"' in script
    assert "item.open = true" in script
    assert "item.open = false" in script


def test_the_print_stylesheet_unclips_tables_and_forces_light_colours():
    css = Path(finders.find("workouts/app.css")).read_text(encoding="utf-8")
    printed = css[css.index("@media print") :]

    assert ".table-wrap {\n    overflow: visible;\n  }" in printed
    assert "break-inside: avoid" in printed
    assert ':root[data-theme="dark"]' in printed
    assert "--bg: #fff;" in printed


@pytest.mark.django_db
def test_the_empty_sessions_state_is_illustrated(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    client.force_login(user)

    content = client.get(reverse("sessions")).content.decode()

    assert content.count('class="empty-icon"') == 1
    assert "No sessions yet." in content


@pytest.mark.django_db
def test_the_filtered_empty_state_uses_a_search_icon(client):
    user = session_with_data()
    client.force_login(user)

    content = client.get(reverse("sessions"), {"q": "nothing-matches"}).content.decode()

    assert content.count('class="empty-icon"') == 1
    assert '<circle cx="11" cy="11" r="6.5"/>' in content


PULL_DAY_CSV = HEADER + "2026-02-10 18:00:00,Pull Day,47m,Barbell Row,1,60,8,0,0,\n"


@pytest.mark.django_db
def test_each_session_row_offers_a_delete_button(client):
    user = session_with_data()
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)

    content = client.get(reverse("sessions")).content.decode()

    assert f'action="{reverse("delete_session", args=[session.pk])}"' in content
    assert "Delete this session" in content


@pytest.mark.django_db
def test_delete_session_removes_only_that_session_and_keeps_the_rest(client):
    user = session_with_data()
    import_workouts_csv(user, PULL_DAY_CSV)
    client.force_login(user)
    ExerciseMeta.objects.filter(owner=user).update(muscle_group="Chest")
    token = ApiToken.objects.create(owner=user, name="laptop", key_hash="b" * 64, prefix="abcdefgh")
    session = WorkoutSession.objects.get(owner=user, workout_name="Axlar")
    other = WorkoutSession.objects.get(owner=user, workout_name="Pull Day")

    response = client.post(reverse("delete_session", args=[session.pk]))

    assert response.status_code == 302
    assert response.url == reverse("sessions")
    assert not WorkoutSession.objects.filter(pk=session.pk).exists()
    assert not WorkoutSet.objects.filter(session_id=session.pk).exists()
    assert WorkoutSession.objects.filter(pk=other.pk).exists()
    assert WorkoutSet.objects.filter(session_id=other.pk).count() == 1
    assert set(ExerciseMeta.objects.filter(owner=user).values_list("muscle_group", flat=True)) == {
        "Chest"
    }
    assert ApiToken.objects.filter(pk=token.pk).exists()
    stash_id = client.session["undo_stash"]
    payload = pending.load_stash(stash_id)
    assert payload["session"]["workout_name"] == "Axlar"
    assert len(payload["sets"]) == 4
    content = client.get(reverse("sessions")).content.decode()
    assert "Undo delete" in content


@pytest.mark.django_db
def test_delete_session_rejects_get_and_other_owners_sessions(client):
    alice = session_with_data("alice")
    bob = session_with_data("bob")
    client.force_login(alice)
    bob_session = WorkoutSession.objects.get(owner=bob)
    own = WorkoutSession.objects.get(owner=alice)

    assert client.post(reverse("delete_session", args=[bob_session.pk])).status_code == 404
    assert client.get(reverse("delete_session", args=[own.pk])).status_code == 405
    assert WorkoutSession.objects.filter(owner=alice).exists()
    assert WorkoutSession.objects.filter(owner=bob).exists()


@pytest.mark.django_db
def test_undo_restores_the_deleted_session_and_its_sets(client):
    user = session_with_data()
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    client.post(reverse("delete_session", args=[session.pk]))
    assert not WorkoutSession.objects.filter(owner=user).exists()
    stash_id = client.session["undo_stash"]

    response = client.post(reverse("undo_delete"), {"stash_id": stash_id}, follow=True)

    assert response.status_code == 200
    restored = WorkoutSession.objects.get(owner=user)
    assert restored.workout_name == "Axlar"
    assert restored.set_count == 4
    assert WorkoutSet.objects.filter(session=restored).count() == 4
    assert "undo_stash" not in client.session
    assert "Restored Axlar with 4 sets." in response.content.decode()
    assert "Undo delete" not in client.get(reverse("sessions")).content.decode()


@pytest.mark.django_db
def test_undo_restores_the_session_the_form_points_at(client):
    user = session_with_data()
    import_workouts_csv(user, PULL_DAY_CSV)
    client.force_login(user)
    axlar = WorkoutSession.objects.get(owner=user, workout_name="Axlar")
    pull = WorkoutSession.objects.get(owner=user, workout_name="Pull Day")
    client.post(reverse("delete_session", args=[axlar.pk]))
    stash_a = client.session["undo_stash"]
    client.post(reverse("delete_session", args=[pull.pk]))
    stash_b = client.session["undo_stash"]

    client.post(reverse("undo_delete"), {"stash_id": stash_a})

    assert WorkoutSession.objects.filter(owner=user, workout_name="Axlar").exists()
    assert not WorkoutSession.objects.filter(owner=user, workout_name="Pull Day").exists()
    assert pending.load_stash(stash_b) is not None


@pytest.mark.django_db
def test_oversized_session_requires_confirmation_before_deleting(client, monkeypatch):
    user = session_with_data()
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    monkeypatch.setattr(pending, "STASH_MAX_BYTES", 10)

    response = client.post(reverse("delete_session", args=[session.pk]))

    assert response.status_code == 302
    assert response.url == f"{reverse('sessions')}?confirm_delete={session.pk}"
    assert WorkoutSession.objects.filter(pk=session.pk).exists()
    confirming = client.get(reverse("sessions"), {"confirm_delete": session.pk}).content.decode()
    assert "Really delete this session (no undo)" in confirming

    response = client.post(
        reverse("delete_session", args=[session.pk]), {"confirm": "1"}, follow=True
    )

    assert not WorkoutSession.objects.filter(pk=session.pk).exists()
    assert "No undo backup was kept because the session is too large." in response.content.decode()


@pytest.mark.django_db
def test_undo_after_a_reimport_does_not_duplicate_rows(client):
    user = session_with_data()
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    client.post(reverse("delete_session", args=[session.pk]))
    stash_id = client.session["undo_stash"]
    import_workouts_csv(user, GROUPED_CSV)

    client.post(reverse("undo_delete"), {"stash_id": stash_id})

    assert WorkoutSession.objects.filter(owner=user).count() == 1
    assert WorkoutSet.objects.filter(owner=user).count() == 4


@pytest.mark.django_db
def test_undo_without_a_stash_reports_nothing_to_undo(client):
    user = session_with_data()
    client.force_login(user)

    response = client.post(reverse("undo_delete"), follow=True)

    assert response.status_code == 200
    assert "There is nothing to undo." in response.content.decode()
    assert WorkoutSession.objects.filter(owner=user).count() == 1


@pytest.mark.django_db
def test_undo_with_a_missing_stash_reports_expiry(client):
    user = session_with_data()
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    client.post(reverse("delete_session", args=[session.pk]))
    stash_id = client.session["undo_stash"]
    pending.discard_stash(stash_id)

    response = client.post(reverse("undo_delete"), {"stash_id": stash_id}, follow=True)

    assert response.status_code == 200
    assert "The undo backup expired or was not found." in response.content.decode()
    assert not WorkoutSession.objects.filter(owner=user).exists()


@pytest.mark.django_db
def test_undo_with_a_corrupt_stash_reports_it_unreadable(client):
    user = session_with_data()
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    client.post(reverse("delete_session", args=[session.pk]))
    stash_id = client.session["undo_stash"]
    pending.save_stash(stash_id, {"owner_id": user.id, "session": {}})

    response = client.post(reverse("undo_delete"), {"stash_id": stash_id}, follow=True)

    assert response.status_code == 200
    assert "The undo backup could not be read." in response.content.decode()
    assert not WorkoutSession.objects.filter(owner=user).exists()
