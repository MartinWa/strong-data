from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.db import OperationalError, connection
from django.test import override_settings
from django.urls import reverse

from workouts import pending, views
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


def newest_undo_stash(client):
    return next(reversed(client.session[views.UNDO_STASHES_KEY]))


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
    stash_id = newest_undo_stash(client)
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
    stash_id = newest_undo_stash(client)

    response = client.post(reverse("undo_delete"), {"stash_id": stash_id}, follow=True)

    assert response.status_code == 200
    restored = WorkoutSession.objects.get(owner=user)
    assert restored.workout_name == "Axlar"
    assert restored.set_count == 4
    assert WorkoutSet.objects.filter(session=restored).count() == 4
    assert views.UNDO_STASHES_KEY not in client.session
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
    stash_a = newest_undo_stash(client)
    client.post(reverse("delete_session", args=[pull.pk]))
    stash_b = newest_undo_stash(client)

    content = client.get(reverse("sessions")).content.decode()
    assert 'aria-labelledby="undo-heading"' in content
    assert content.index(f'value="{stash_b}"') < content.index(f'value="{stash_a}"')

    response = client.post(reverse("undo_delete"), {"stash_id": stash_a}, follow=True)

    assert WorkoutSession.objects.filter(owner=user, workout_name="Axlar").exists()
    assert not WorkoutSession.objects.filter(owner=user, workout_name="Pull Day").exists()
    assert pending.load_stash(stash_b) is not None
    assert f'value="{stash_b}"' in response.content.decode()


@pytest.mark.django_db
def test_oversized_session_requires_confirmation_before_deleting(client, monkeypatch):
    user = session_with_data()
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    monkeypatch.setattr(pending, "STASH_MAX_BYTES", 10)

    response = client.post(reverse("delete_session", args=[session.pk]))

    assert response.status_code == 302
    assert response.url == f"{reverse('sessions')}?confirm_delete={session.pk}&open={session.pk}"
    assert WorkoutSession.objects.filter(pk=session.pk).exists()
    confirming = client.get(reverse("sessions"), {"confirm_delete": session.pk}).content.decode()
    assert "Really delete this session (no undo)" in confirming

    response = client.post(
        reverse("delete_session", args=[session.pk]), {"confirm": "1"}, follow=True
    )

    assert not WorkoutSession.objects.filter(pk=session.pk).exists()
    assert "No undo backup was kept." in response.content.decode()


@pytest.mark.django_db
def test_delete_aborts_when_the_backup_cannot_be_written(client, monkeypatch):
    user = session_with_data()
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    monkeypatch.setattr(pending, "save_stash", lambda *args: False)

    response = client.post(reverse("delete_session", args=[session.pk]), follow=True)

    assert WorkoutSession.objects.filter(pk=session.pk).exists()
    assert "The undo backup could not be written, so the session was not deleted." in (
        response.content.decode()
    )

    response = client.post(
        reverse("delete_session", args=[session.pk]), {"confirm": "1"}, follow=True
    )

    assert not WorkoutSession.objects.filter(pk=session.pk).exists()
    assert "No undo backup was kept." in response.content.decode()


@pytest.mark.django_db
def test_delete_on_locked_database_keeps_session_and_discards_backup(client):
    user = session_with_data()
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)

    def lock_on_set_delete(execute, sql, params, many, context):
        if sql.startswith('DELETE FROM "workouts_workoutset"'):
            assert list(pending.undo_dir().glob("*.json"))
            raise OperationalError("database is locked")
        return execute(sql, params, many, context)

    with connection.execute_wrapper(lock_on_set_delete):
        response = client.post(reverse("delete_session", args=[session.pk]), follow=True)

    assert response.status_code == 200
    assert "Please try deleting the session again." in response.content.decode()
    assert WorkoutSession.objects.filter(pk=session.pk).exists()
    assert WorkoutSet.objects.filter(session=session).count() == 4
    assert views.UNDO_STASHES_KEY not in client.session
    assert list(pending.undo_dir().glob("*.json")) == []

    response = client.post(reverse("delete_session", args=[session.pk]), follow=True)

    assert response.status_code == 200
    assert not WorkoutSession.objects.filter(pk=session.pk).exists()
    assert pending.load_stash(newest_undo_stash(client)) is not None


@pytest.mark.django_db
def test_oversized_delete_confirmation_keeps_the_current_page_and_filters(client, monkeypatch):
    user = get_user_model().objects.create_user(username="alice", password="x")
    rows = "\n".join(
        f"2026-01-{day:02d} 09:00:00,Push Day,54m,Bench Press,1,80,5,0,0,8" for day in range(1, 27)
    )
    import_workouts_csv(user, HEADER + rows + "\n")
    client.force_login(user)
    monkeypatch.setattr(pending, "STASH_MAX_BYTES", 10)
    target = WorkoutSession.objects.filter(owner=user).order_by("session_date", "id").first()

    content = client.get(reverse("sessions"), {"page": 2, "q": "Push"}).content.decode()
    marker = f"/sessions/{target.pk}/delete/"
    index = content.index(marker)
    action = content[content.rindex('action="', 0, index) + 8 : content.index('"', index)]
    assert "page=2" in action
    assert "q=Push" in action

    response = client.post(action)

    assert response.status_code == 302
    assert "page=2" in response.url
    assert "q=Push" in response.url
    assert f"confirm_delete={target.pk}" in response.url
    assert f"open={target.pk}" in response.url
    confirming = client.get(response.url).content.decode()
    assert "Really delete this session (no undo)" in confirming
    assert confirming.count("data-print-open open>") == 1


@pytest.mark.django_db
@pytest.mark.parametrize(("backup_orders", "reimported_order"), [((1, 2), 1), ((1,), 2)])
def test_undo_restores_identical_valued_sets_with_different_orders(
    client, backup_orders, reimported_order
):
    user = get_user_model().objects.create_user(username="alice", password="x")
    text = HEADER + "".join(
        f"2026-01-05 09:00:00,Axlar,54m,Bench Press,{order},80,5,0,0,8\n" for order in backup_orders
    )
    import_workouts_csv(user, text)
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    client.post(reverse("delete_session", args=[session.pk]))
    stash_id = newest_undo_stash(client)
    fragment = HEADER + (
        f"2026-01-05 09:00:00,Axlar,54m,Bench Press,{reimported_order},80,5,0,0,8\n"
    )
    import_workouts_csv(user, fragment)

    client.post(reverse("undo_delete"), {"stash_id": stash_id})

    sets = WorkoutSet.objects.filter(owner=user)
    assert sets.count() == 2
    assert sorted(sets.values_list("set_order", flat=True)) == [1, 2]


@pytest.mark.django_db
@pytest.mark.parametrize(("fragment_duration", "expected_duration"), [("", 54), ("0m", 0)])
def test_undo_after_partial_reimport_does_not_duplicate_sets(
    client, fragment_duration, expected_duration
):
    user = get_user_model().objects.create_user(username="alice", password="x")
    duplicate = HEADER + (
        "2026-01-05 09:00:00,Axlar, 54m,Bench Press (Barbell),1,80,5,0,0,8\n"
        "2026-01-05 09:00:00,Axlar, 54m,Bench Press (Barbell),1,90,5,0,0,8\n"
    )
    import_workouts_csv(user, duplicate)
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    client.post(reverse("delete_session", args=[session.pk]))
    stash_id = newest_undo_stash(client)
    fragment = (
        HEADER
        + f"2026-01-05 09:00:00,Axlar,{fragment_duration},Bench Press (Barbell),1,90,5,0,0,8\n"
    )
    import_workouts_csv(user, fragment)

    client.post(reverse("undo_delete"), {"stash_id": stash_id})

    sets = WorkoutSet.objects.filter(owner=user)
    assert sets.count() == 2
    assert sorted(sets.values_list("weight_kg", flat=True)) == [
        Decimal("80.00"),
        Decimal("90.00"),
    ]
    assert WorkoutSession.objects.get(owner=user).duration_min == expected_duration
    result = import_workouts_csv(user, duplicate)
    assert (result.added_sets, result.skipped_sets, result.conflicted) == (0, 2, 0)


@pytest.mark.django_db
def test_undo_volume_overflow_keeps_the_backup_for_retry(client):
    user = get_user_model().objects.create_user(username="alice", password="x")
    big = HEADER + "2026-01-05 08:30:00,Push Day,54m,Bench,1,600000,10000,0,0,8\n"
    import_workouts_csv(user, big)
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    client.post(reverse("delete_session", args=[session.pk]))
    stash_id = newest_undo_stash(client)
    fragment = HEADER + "2026-01-05 08:30:00,Push Day,54m,Bench,1,900000,10000,0,0,8\n"
    import_workouts_csv(user, fragment)

    response = client.post(reverse("undo_delete"), {"stash_id": stash_id}, follow=True)

    assert "cannot be restored yet" in response.content.decode()
    assert pending.load_stash(stash_id) is not None
    assert stash_id in client.session[views.UNDO_STASHES_KEY]
    assert WorkoutSet.objects.filter(owner=user).count() == 1

    replacement = WorkoutSession.objects.get(owner=user)
    response = client.post(reverse("delete_session", args=[replacement.pk]), follow=True)
    assert f'value="{stash_id}"' in response.content.decode()

    response = client.post(reverse("undo_delete"), {"stash_id": stash_id}, follow=True)
    assert "Restored Push Day with 1 set." in response.content.decode()
    assert WorkoutSet.objects.get(owner=user).weight_kg == Decimal("600000.00")


@pytest.mark.django_db
def test_undo_merges_into_a_session_reimported_in_a_new_zone(client):
    with override_settings(TIME_ZONE="UTC"):
        user = session_with_data()
        client.force_login(user)
        session = WorkoutSession.objects.get(owner=user)
        client.post(reverse("delete_session", args=[session.pk]))
        stash_id = newest_undo_stash(client)

    fragment = "\n".join(GROUPED_CSV.splitlines()[:2]) + "\n"
    with override_settings(TIME_ZONE="Europe/Stockholm"):
        import_workouts_csv(user, fragment)
        client.post(reverse("undo_delete"), {"stash_id": stash_id})
        result = import_workouts_csv(user, GROUPED_CSV)

    session = WorkoutSession.objects.get(owner=user)
    assert session.import_time_zone == "Europe/Stockholm"
    assert session.set_count == 4
    assert session.sets.order_by("set_time").first().set_time == datetime(
        2026, 1, 5, 8, 0, tzinfo=UTC
    )
    assert (result.added_sets, result.skipped_sets) == (0, 4)


@pytest.mark.django_db
def test_undo_on_locked_database_keeps_backup_for_retry(client, monkeypatch):
    user = session_with_data()
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    client.post(reverse("delete_session", args=[session.pk]))
    stash_id = newest_undo_stash(client)

    def locked_restore(*args):
        raise OperationalError("database is locked")

    with monkeypatch.context() as patch:
        patch.setattr(views, "restore_stash", locked_restore)
        response = client.post(reverse("undo_delete"), {"stash_id": stash_id}, follow=True)

    assert response.status_code == 200
    assert "Please try restoring the session again." in response.content.decode()
    assert pending.load_stash(stash_id) is not None
    assert stash_id in client.session[views.UNDO_STASHES_KEY]

    client.post(reverse("undo_delete"), {"stash_id": stash_id})

    assert WorkoutSet.objects.filter(owner=user).count() == 4
    assert pending.load_stash(stash_id) is None


@pytest.mark.django_db
def test_undo_after_a_reimport_does_not_duplicate_rows(client):
    user = session_with_data()
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    client.post(reverse("delete_session", args=[session.pk]))
    stash_id = newest_undo_stash(client)
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
    stash_id = newest_undo_stash(client)
    pending.discard_stash(stash_id)

    response = client.post(reverse("undo_delete"), {"stash_id": stash_id}, follow=True)

    assert response.status_code == 200
    assert "The undo backup expired or was not found." in response.content.decode()
    assert not WorkoutSession.objects.filter(owner=user).exists()
    assert views.UNDO_STASHES_KEY not in client.session
    assert "Undo delete" not in client.get(reverse("sessions")).content.decode()


@pytest.mark.django_db
def test_undo_with_a_corrupt_stash_reports_it_unreadable(client):
    user = session_with_data()
    client.force_login(user)
    session = WorkoutSession.objects.get(owner=user)
    client.post(reverse("delete_session", args=[session.pk]))
    stash_id = newest_undo_stash(client)
    pending.save_stash(stash_id, {"owner_id": user.id, "session": {}})

    response = client.post(reverse("undo_delete"), {"stash_id": stash_id}, follow=True)

    assert response.status_code == 200
    assert "The undo backup could not be read." in response.content.decode()
    assert not WorkoutSession.objects.filter(owner=user).exists()
