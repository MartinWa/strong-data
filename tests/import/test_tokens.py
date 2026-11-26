import hashlib
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from workouts.models import ApiToken


@pytest.mark.django_db
def test_generate_returns_the_secret_and_stores_only_hash_and_prefix():
    user = get_user_model().objects.create_user(username="alice", password="x")

    token, secret = ApiToken.generate(user, "laptop")

    assert len(secret) >= 32
    assert token.pk is not None
    assert token.owner == user
    assert token.name == "laptop"
    assert token.expires_at is None
    assert token.prefix == secret[:8]
    assert token.key_hash == hashlib.sha256(secret.encode()).hexdigest()
    assert ApiToken.objects.count() == 1


@pytest.mark.django_db
def test_generate_passes_expiry_through():
    user = get_user_model().objects.create_user(username="alice", password="x")
    expires_at = timezone.now() + timezone.timedelta(days=30)

    token, _secret = ApiToken.generate(user, "laptop", expires_at=expires_at)

    assert token.expires_at == expires_at


@pytest.mark.django_db
def test_generate_asserts_on_a_short_secret():
    user = get_user_model().objects.create_user(username="alice", password="x")

    with (
        mock.patch("workouts.models.secrets.token_urlsafe", return_value="short"),
        pytest.raises(AssertionError, match="too short"),
    ):
        ApiToken.generate(user, "laptop")

    assert ApiToken.objects.count() == 0
