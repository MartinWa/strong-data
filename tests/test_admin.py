import hashlib

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.urls import reverse

from workouts.models import ApiToken, Exercise, ExerciseMeta, WorkoutSession, WorkoutSet
from workouts.services import import_workouts_csv

CSV = (
    "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
    "2026-01-05 09:00:00,Push Day #1,54m,Bench Press (Barbell),1,80,5,0,0,8.0\n"
    "2026-01-05 09:05:00,Push Day #1,54m,Chest Fly,1,,,0,0,7.0\n"
)

SECRET = "synthetic-admin-token-secret"
MODELS = [
    "exercise",
    "exercisemeta",
    "workoutsession",
    "workoutset",
    "apitoken",
]


@pytest.fixture
def staff(db):
    user = get_user_model().objects.create_user(
        "admin-staff",
        password="synthetic-password-1",
        is_staff=True,
        is_superuser=True,
    )
    import_workouts_csv(user, CSV)
    ApiToken.objects.create(
        owner=user,
        name="laptop",
        key_hash=hashlib.sha256(SECRET.encode()).hexdigest(),
        prefix=SECRET[:8],
    )
    return user


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


def test_all_workout_models_are_registered():
    registered = {model.__name__.lower() for model in admin.site._registry}
    assert set(MODELS) <= registered


def test_superuser_can_browse_every_changelist(staff_client):
    for name in MODELS:
        response = staff_client.get(reverse(f"admin:workouts_{name}_changelist"))
        assert response.status_code == 200, name


def test_registrations_stay_read_only_without_permissions(client, db):
    staff_only = get_user_model().objects.create_user(
        "staff-no-perms", password="synthetic-password-1", is_staff=True
    )
    client.force_login(staff_only)
    index = client.get(reverse("admin:index"))
    assert index.status_code == 200
    assert reverse("admin:workouts_workoutsession_changelist") not in index.content.decode()
    assert client.get(reverse("admin:workouts_apitoken_changelist")).status_code == 403


def test_token_views_never_show_the_hash_or_the_secret(staff_client):
    token = ApiToken.objects.get()
    for url in [
        reverse("admin:workouts_apitoken_changelist"),
        reverse("admin:workouts_apitoken_change", args=[token.pk]),
    ]:
        body = staff_client.get(url).content.decode()
        assert token.key_hash not in body, url
        assert SECRET not in body, url


def test_admin_is_read_only(staff_client):
    token = ApiToken.objects.get()
    add = staff_client.get(reverse("admin:workouts_apitoken_add"))
    assert add.status_code == 403
    delete_url = reverse("admin:workouts_apitoken_delete", args=[token.pk])
    delete = staff_client.post(delete_url, {"post": "yes"})
    assert delete.status_code == 403
    assert ApiToken.objects.filter(pk=token.pk).exists()

    change = staff_client.get(reverse("admin:workouts_apitoken_change", args=[token.pk]))
    assert delete_url not in change.content.decode()
    changelist = staff_client.get(reverse("admin:workouts_workoutset_changelist"))
    assert 'name="action"' not in changelist.content.decode()


def account_with_data(username):
    user = get_user_model().objects.create_user(username, password="synthetic-password-1")
    import_workouts_csv(user, CSV)
    secret = f"{SECRET}-{username}"
    ApiToken.objects.create(
        owner=user,
        name="laptop",
        key_hash=hashlib.sha256(secret.encode()).hexdigest(),
        prefix=secret[:8],
    )
    return user


def assert_account_is_gone(user):
    assert not get_user_model().objects.filter(pk=user.pk).exists()
    for model in (Exercise, ExerciseMeta, WorkoutSession, WorkoutSet, ApiToken):
        assert not model.objects.filter(owner_id=user.pk).exists(), model.__name__


def test_superuser_can_delete_an_account_that_owns_workout_data(staff_client):
    victim = account_with_data("deleted-user")
    url = reverse("admin:auth_user_delete", args=[victim.pk])
    confirmation = staff_client.get(url)
    assert confirmation.status_code == 200
    assert "Cannot delete" not in confirmation.content.decode()
    assert staff_client.post(url, {"post": "yes"}).status_code == 302
    assert_account_is_gone(victim)


def test_superuser_can_bulk_delete_accounts_from_the_changelist(staff_client):
    victim = account_with_data("bulk-deleted-user")
    url = reverse("admin:auth_user_changelist")
    selection = {"action": "delete_selected", "_selected_action": [victim.pk], "index": 0}
    confirmation = staff_client.post(url, selection)
    assert confirmation.status_code == 200
    assert "Cannot delete" not in confirmation.content.decode()
    assert staff_client.post(url, {**selection, "post": "yes"}).status_code == 302
    assert_account_is_gone(victim)


def test_non_staff_cannot_reach_the_admin(staff_client):
    staff_client.logout()
    user = get_user_model().objects.create_user("plain-user", password="synthetic-password-1")
    staff_client.force_login(user)
    response = staff_client.get(reverse("admin:index"))
    assert response.status_code == 302
    assert reverse("admin:login") in response["Location"]


def test_admin_link_only_for_staff(staff_client):
    staff_page = staff_client.get(reverse("sessions")).content.decode()
    assert f'href="{reverse("admin:index")}"' in staff_page
    assert staff_page.index("Admin") > staff_page.index("</nav>")

    staff_client.logout()
    user = get_user_model().objects.create_user("second-user", password="synthetic-password-1")
    staff_client.force_login(user)
    plain_page = staff_client.get(reverse("sessions")).content.decode()
    assert reverse("admin:index") not in plain_page
