import hashlib

import pytest
from django.contrib.auth import get_user_model

from workouts.models import ApiToken
from workouts.services import import_workouts_csv

CSV = (
    "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
    "2026-01-05 09:00:00,Push Day #1,54m,Bench Press (Barbell),1,80,5,0,0,8.0\n"
    "2026-01-05 09:05:00,Push Day #1,54m,Bench Press (Barbell),2,82.5,3,0,0,8.5\n"
    "2026-01-05 09:10:00,Push Day #1,54m,Chest Fly,1,,,0,0,\n"
    "2026-01-07 08:00:00,Pull Day #2,1h 2m,Seated Row (Cable),1,60,10,0,0,9.0\n"
    "2026-01-07 08:05:00,Pull Day #2,1h 2m,Pull Up,1,,,0,0,\n"
    "2026-02-02 07:30:00,Push Day #2,45m,Bench Press (Barbell),1,85,5,0,0,9.0\n"
    "2026-02-02 07:35:00,Push Day #2,45m,Overhead Press,1,40,8,0,0,7.5\n"
)

OTHER_CSV = (
    "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
    "2026-03-01 10:00:00,Secret Session,30m,Squat (Barbell),1,100,5,0,0,9.0\n"
)

SECRET = "synthetic-token-for-alice"


def make_user(username, csv_text, secret):
    user = get_user_model().objects.create_user(username=username, password="x")
    import_workouts_csv(user, csv_text)
    ApiToken.objects.create(
        owner=user,
        name="reader",
        key_hash=hashlib.sha256(secret.encode()).hexdigest(),
        prefix=secret[:8],
    )
    return user


@pytest.fixture
def alice(db):
    return make_user("alice", CSV, SECRET)


@pytest.fixture
def bob(db):
    return make_user("bob", OTHER_CSV, "synthetic-token-for-bob")


@pytest.fixture
def auth(client, alice):
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {SECRET}"
    return client
