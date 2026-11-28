from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from workouts.services import import_workouts_csv
from workouts.views import MAX_UPLOAD_BYTES, TOO_LARGE_MESSAGE

HEADER = "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"

MINIMAL = HEADER + "2026-01-05 09:00:00,Push Day,54m,Bench Press (Barbell),1,80,5,0,0,8\n"

TWO_SESSIONS = (
    HEADER
    + "2026-01-05 09:00:00,Push Day,54m,Bench Press (Barbell),1,80,5,0,0,8\n"
    + "2026-01-05 09:05:00,Push Day,54m,Chest Fly,1,20,12,0,0,8\n"
    + "2026-02-10 18:00:00,Pull Day,47m,Barbell Row,1,60,8,0,0,\n"
)

WARNINGS_CSV = (
    HEADER
    + "".join(
        f"2026-01-05 09:{minute:02d}:00,Push Day,54m,Exercise {minute:02d},1,80,5,0,0,99\n"
        for minute in range(60)
    )
    + "".join(
        f"2026-01-06 09:{minute:02d}:00,Pull Day,47m,Bad Weight {minute},1,abc,5,0,0,8\n"
        for minute in range(3)
    )
)

TWELVE_SESSIONS = HEADER + "".join(
    f"2026-01-{day:02d} 09:00:00,Push Day,54m,Bench Press,1,80,5,0,0,8\n" for day in range(1, 13)
)


@pytest.fixture(autouse=True)
def pending_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("STRONG_PENDING_DIR", str(tmp_path / "pending"))


def signed_in(client, username="alice"):
    user = get_user_model().objects.create_user(username=username, password="x")
    client.force_login(user)
    return user


def upload(client, text=MINIMAL):
    return client.post(
        reverse("upload"),
        {"csv_file": SimpleUploadedFile("export.csv", text.encode(), content_type="text/csv")},
    )


@pytest.mark.django_db
def test_upload_page_says_nothing_about_replacing_on_a_first_run(client):
    signed_in(client)

    content = client.get(reverse("upload")).content.decode()

    assert "This is your first import." not in content
    assert "nothing will be replaced" not in content
    assert "An import replaces" not in content
    assert "Confirming replaces your data" not in content


@pytest.mark.django_db
def test_upload_page_says_nothing_about_replacing_once_sessions_exist(client):
    user = signed_in(client)
    import_workouts_csv(user, TWO_SESSIONS)

    content = client.get(reverse("upload")).content.decode()

    assert "This is your first import." not in content
    assert "replaces" not in content
    assert "An import replaces" not in content


@pytest.mark.django_db
def test_upload_page_explains_how_to_export_from_strong(client):
    signed_in(client)

    content = client.get(reverse("upload")).content.decode()

    assert "<summary>How to export from Strong</summary>" in content
    assert "Export workouts" in content
    assert content.index('<details class="export-help">') < content.index("Export workouts")


@pytest.mark.django_db
def test_upload_field_states_the_size_limit_and_is_described_by_it(client):
    signed_in(client)

    content = client.get(reverse("upload")).content.decode()

    assert 'aria-describedby="id_csv_file_helptext"' in content
    assert 'id="id_csv_file_helptext"' in content
    assert "Up to 10 MB." in content


@pytest.mark.django_db
def test_upload_autosubmits_when_a_file_is_chosen(client):
    signed_in(client)

    content = client.get(reverse("upload")).content.decode()

    assert "data-upload-form" in content
    assert 'src="/static/workouts/upload.js"' in content
    noscript = content[content.index("<noscript>") : content.index("</noscript>")]
    assert ">Preview<" in noscript
    assert content.count(">Preview<") == 1


@pytest.mark.django_db
def test_upload_size_limit_reaches_the_browser_from_the_server_constant(client):
    signed_in(client)

    content = client.get(reverse("upload")).content.decode()

    assert f'data-max-bytes="{MAX_UPLOAD_BYTES}"' in content
    assert f'data-too-large="{TOO_LARGE_MESSAGE}"' in content
    assert 'id="id_csv_file_client_error"' in content
    assert 'role="status"' in content


@pytest.mark.django_db
def test_upload_picker_only_offers_csv_files(client):
    signed_in(client)

    content = client.get(reverse("upload")).content.decode()

    assert 'accept=".csv,text/csv"' in content


@pytest.mark.django_db
def test_preview_states_what_the_import_merges(client):
    user = signed_in(client)
    import_workouts_csv(user, TWO_SESSIONS)

    upload(client)
    content = client.get(reverse("preview")).content.decode()

    assert "Confirming adds 0 sessions and 0 sets. 1 session already stored." in content
    assert "Skipping 1 set already stored or repeated in the file." in content
    assert "This file ends 2026-01-05; you already have data through 2026-02-10." in content
    assert "Nothing stored is deleted." in content
    assert "replaces" not in content
    assert "Muscle-group corrections are kept." in content


@pytest.mark.django_db
def test_preview_counts_new_and_existing_sessions_and_sets(client):
    user = signed_in(client)
    import_workouts_csv(user, TWO_SESSIONS)
    extra = (
        HEADER
        + "2026-01-05 09:00:00,Push Day,54m,Bench Press (Barbell),1,80,5,0,0,8\n"
        + "2026-03-01 10:00:00,Legs Day,60m,Squat,1,100,5,0,0,9\n"
    )

    upload(client, extra)
    content = client.get(reverse("preview")).content.decode()

    assert "Confirming adds 1 session and 1 set. 1 session already stored." in content
    assert "Skipping 1 set already stored or repeated in the file." in content
    assert "This file ends" not in content


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("weight", "rpe", "change"),
    [("80", "9", "rpe: 8 → 9"), ("80.004", "8", "volume: 400 → 400.02")],
)
def test_preview_reports_conflicts_with_the_changed_field_shown(client, weight, rpe, change):
    user = signed_in(client)
    import_workouts_csv(user, TWO_SESSIONS)
    conflicting = (
        HEADER + f"2026-01-05 09:00:00,Push Day,54m,Bench Press (Barbell),1,{weight},5,0,0,{rpe}\n"
    )

    upload(client, conflicting)
    content = client.get(reverse("preview")).content.decode()

    assert "1 stored set differs from this file; stored values are kept." in content
    assert "Confirming adds 0 sessions and 0 sets. 1 session already stored." in content
    conflicts_card = content[content.index("<h2>Conflicts</h2>") :]
    assert '<th scope="col" class="nowrap">Date</th>' in conflicts_card
    assert '<td class="muted nowrap">2026-01-05</td>' in conflicts_card
    assert "Bench Press (Barbell)" in conflicts_card
    assert "Push Day" in conflicts_card
    assert change in conflicts_card


@pytest.mark.django_db
def test_preview_labels_in_file_duplicates_as_skipped(client):
    user = signed_in(client)
    import_workouts_csv(user, TWO_SESSIONS)
    duplicate = (
        HEADER
        + "2026-03-01 10:00:00,Legs Day,60m,Squat,1,100,5,0,0,9\n"
        + "2026-03-01 10:00:00,Legs Day,60m,Squat,1,100,5,0,0,9\n"
    )

    upload(client, duplicate)
    content = client.get(reverse("preview")).content.decode()

    assert "Confirming adds 1 session and 1 set. 0 sessions already stored." in content
    assert "Skipping 1 set already stored or repeated in the file." in content


@pytest.mark.django_db
def test_preview_on_a_first_run_is_not_destructive(client):
    signed_in(client)

    upload(client)
    content = client.get(reverse("preview")).content.decode()

    assert "This is your first import." in content
    assert "nothing will be deleted" in content
    assert "replaces" not in content


@pytest.mark.django_db
def test_preview_keeps_the_confirm_action_in_a_sticky_bar(client):
    signed_in(client)

    upload(client)
    content = client.get(reverse("preview")).content.decode()

    assert '<div class="card action-bar">' in content
    assert "Confirm import" in content
    assert "data-submit-once" in content
    assert 'src="/static/workouts/submit-once.js"' in content

    form = content[content.index('<form method="post" class="actions">') :]
    form = form[: form.index("</form>")]
    assert 'name="action" value="confirm"' in form
    assert 'name="action" value="cancel"' in form
    assert "{% csrf_token %}" not in form
    assert "csrfmiddlewaretoken" in form


@pytest.mark.django_db
def test_preview_groups_warnings_by_cause_with_counts(client):
    signed_in(client)

    upload(client, WARNINGS_CSV)
    content = client.get(reverse("preview")).content.decode()

    assert "63 rows affected" in content
    assert "60 rows" in content
    assert "3 rows" in content
    assert content.count("invalid RPE; stored as null") == 1
    assert content.count("invalid weight; stored as null") == 1
    assert "and 40 more" in content
    assert "badge-danger" not in content


@pytest.mark.django_db
def test_preview_labels_the_warning_count_as_affected_rows(client):
    signed_in(client)

    upload(
        client,
        HEADER + "2026-01-05 09:00:00,Push Day,54m,Bench Press (Barbell),1,abc,5,0,0,99\n",
    )
    content = client.get(reverse("preview")).content.decode()

    assert "1 row affected" in content
    assert "2 rows affected" not in content
    assert content.count("invalid weight; stored as null") == 1
    assert content.count("invalid RPE; stored as null") == 1


@pytest.mark.django_db
def test_preview_lists_every_session_without_a_show_all_block(client):
    signed_in(client)

    upload(client, TWELVE_SESSIONS)
    content = client.get(reverse("preview")).content.decode()

    assert "Show all" not in content
    assert "Showing the first 10" not in content
    for day in range(1, 13):
        assert f"2026-01-{day:02d}" in content
    assert content.index("2026-01-12") < content.index("2026-01-03")
    assert content.index("2026-01-03") < content.index("2026-01-01")


@pytest.mark.django_db
def test_preview_caps_the_session_table_at_the_newest_200(client):
    signed_in(client)
    start = date(2026, 1, 1)
    rows = (
        f"{(start + timedelta(days=offset)).isoformat()} 09:00:00,"
        "Push Day,54m,Bench Press,1,80,5,0,0,8"
        for offset in range(205)
    )
    many_sessions = HEADER + "".join(f"{row}\n" for row in rows)

    upload(client, many_sessions)
    content = client.get(reverse("preview")).content.decode()

    assert "Showing the newest 200 of 205 sessions." in content
    assert '<span class="stat-value">205</span>' in content
    assert "Show all" not in content
    assert "2026-07-24" in content
    assert "2026-01-06" in content
    assert "2026-01-05" not in content


@pytest.mark.django_db
def test_preview_lists_sessions_newest_first_like_the_sessions_page(client):
    signed_in(client)

    upload(client, TWO_SESSIONS)
    content = client.get(reverse("preview")).content.decode()

    assert content.index('<td class="nowrap">2026-02-10</td>') < content.index(
        '<td class="nowrap">2026-01-05</td>'
    )
    sample = content[content.index("Sample sets") :]
    assert sample.index("Barbell Row") < sample.index("Chest Fly")
    assert "2026-02-10 18:00" in sample
    assert sample.count('class="sample-group"') == 3


@pytest.mark.django_db
def test_preview_sample_sets_are_grouped_by_exercise(client):
    signed_in(client)

    upload(client, TWO_SESSIONS)
    content = client.get(reverse("preview")).content.decode()
    sample = content[content.index("Sample sets") :]
    groups = [part.split("</tr>")[0] for part in sample.split('class="sample-group"')[1:]]

    assert len(groups) == 3
    assert "2026-02-10" in groups[0]
    assert "Pull Day" in groups[0]
    assert "Barbell Row" in groups[0]
    assert "2026-01-05" in groups[1]
    assert "Push Day" in groups[1]
    assert "Bench Press" in groups[1]
    assert "Chest Fly" in groups[2]
    assert "2026-01-05" not in groups[2]
    assert '<th scope="col">Exercise</th>' not in sample


@pytest.mark.django_db
def test_preview_sample_sets_label_the_set_number_and_trim_the_time(client):
    signed_in(client)

    upload(client)
    content = client.get(reverse("preview")).content.decode()

    assert '<th scope="col" class="num">Set</th>' in content
    assert "2026-01-05 09:00" in content
    assert "09:00:00" not in content


@pytest.mark.django_db
def test_preview_marks_secondary_columns_for_phones(client):
    signed_in(client)

    upload(client)
    content = client.get(reverse("preview")).content.decode()

    assert 'class="nowrap">Date</th>' in content
    assert '<th scope="col" class="secondary">Program</th>' in content
    assert '<th scope="col" class="num secondary">Volume (kg)</th>' in content


@pytest.mark.django_db
def test_visiting_preview_without_a_pending_import_explains_the_redirect(client):
    signed_in(client)

    response = client.get(reverse("preview"), follow=True)

    assert response.redirect_chain == [(reverse("upload"), 302)]
    content = response.content.decode()
    assert "Your preview expired or was not found. Upload the CSV again." in content


@pytest.mark.django_db
def test_the_picker_sits_in_a_dropzone_that_keeps_the_file_input(client):
    signed_in(client)

    content = client.get(reverse("upload")).content.decode()

    assert '<div class="dropzone" data-dropzone>' in content
    assert "Drag a CSV export here" in content
    assert content.index("data-dropzone") < content.index('id="id_csv_file"')


def test_the_dropzone_reuses_the_input_and_its_size_check():
    from pathlib import Path

    from django.contrib.staticfiles import finders

    script = Path(finders.find("workouts/upload.js")).read_text(encoding="utf-8")

    assert "input.files = transfer.files" in script
    assert 'input.dispatchEvent(new Event("change", { bubbles: true }))' in script
    assert "form.requestSubmit()" in script
    assert "is-dragging" in script


def listener_body(script, anchor):
    start = script.index(anchor)
    return script[start : script.index("\n  });", start)]


def test_every_drop_on_the_dropzone_takes_the_shared_path():
    from pathlib import Path

    from django.contrib.staticfiles import finders

    script = Path(finders.find("workouts/upload.js")).read_text(encoding="utf-8")
    entering = listener_body(script, '["dragenter", "dragover"].forEach')
    dropped = listener_body(script, 'dropzone.addEventListener("drop"')

    for body in (entering, dropped):
        assert 'input[type="file"]' not in body
        assert "if (!canHandle(event)) return;" in body
        assert "event.preventDefault()" in body

    assert "drop(event.dataTransfer.files)" in dropped
