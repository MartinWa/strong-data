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
def test_preview_states_what_the_import_replaces(client):
    user = signed_in(client)
    import_workouts_csv(user, TWO_SESSIONS)

    upload(client)
    content = client.get(reverse("preview")).content.decode()

    assert "Confirming replaces 2 sessions and 3 sets currently stored." in content
    assert content.count("replaces") == 1
    assert "Muscle-group corrections are kept." in content


@pytest.mark.django_db
def test_preview_on_a_first_run_is_not_destructive(client):
    signed_in(client)

    upload(client)
    content = client.get(reverse("preview")).content.decode()

    assert "This is your first import." in content
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


@pytest.mark.django_db
def test_preview_groups_warnings_by_cause_with_counts(client):
    signed_in(client)

    upload(client, WARNINGS_CSV)
    content = client.get(reverse("preview")).content.decode()

    assert "63 rows" in content
    assert "60 rows" in content
    assert "3 rows" in content
    assert content.count("invalid RPE; stored as null") == 1
    assert content.count("invalid weight; stored as null") == 1
    assert "and 40 more" in content
    assert "badge-danger" not in content


@pytest.mark.django_db
def test_preview_caps_the_session_table_behind_show_all(client):
    signed_in(client)

    upload(client, TWELVE_SESSIONS)
    content = client.get(reverse("preview")).content.decode()

    assert "Showing the first 10 of 12 sessions." in content
    assert "Show all 12 sessions" in content
    assert content.index("2026-01-10") < content.index("Show all 12 sessions")
    tail = content[content.index("Show all 12 sessions") : content.index("Sample sets")]
    assert "2026-01-11" in tail
    assert tail.count("2026-01-11") == 1


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
