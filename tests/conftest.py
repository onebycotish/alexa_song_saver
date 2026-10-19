import json

import pytest
import responses

import config
import lambda_function
from fake_spotify import FakeSpotify

VALID_SECRETS = {
    "client_id": "test-client-id",
    "client_secret": "test-client-secret",
    "refresh_token": "test-refresh-token",
    "authorized_at": "2026-10-01",
}


@pytest.fixture(autouse=True)
def secrets_path(tmp_path, monkeypatch):
    """Point config at a temp secrets file so tests never touch the Owner's real one.

    The file doesn't exist unless a test writes it.
    """
    path = tmp_path / "secrets.json"
    monkeypatch.setattr(config, "SECRETS_PATH", path)
    return path


@pytest.fixture
def write_secrets(secrets_path):
    def write(data=None, **overrides):
        content = dict(VALID_SECRETS, **overrides) if data is None else data
        secrets_path.write_text(content if isinstance(content, str) else json.dumps(content))
    return write


@pytest.fixture
def valid_secrets(write_secrets):
    write_secrets()


@pytest.fixture(autouse=True)
def fresh_container(monkeypatch):
    """Each test starts like a cold Lambda container: no cached Spotify client or token."""
    monkeypatch.setattr(lambda_function, "_client", None)
    monkeypatch.setattr(lambda_function, "_client_key", None)


@pytest.fixture(autouse=True)
def spotify():
    """Every test runs with the network faked; an unregistered request fails the test."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield FakeSpotify(mock)


@pytest.fixture
def spotify_ok(spotify):
    """Spotify answers the happy path: token, a playing track, and a successful save."""
    spotify.token()
    spotify.currently_playing()
    spotify.library_save()
    return spotify
