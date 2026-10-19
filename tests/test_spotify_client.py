import base64

import pytest
import requests
import responses

from spotify_client import (
    CURRENTLY_PLAYING_URL,
    LIBRARY_URL,
    TIMEOUT_SECONDS,
    TOKEN_URL,
    CurrentTrack,
    Forbidden,
    SaveOutcomeUnknown,
    SpotifyClient,
    SpotifyUnavailable,
    TokenRejected,
)


def make_client():
    return SpotifyClient("test-client-id", "test-client-secret", "test-refresh-token")


def test_token_refresh_uses_basic_auth_and_the_refresh_token(spotify):
    spotify.token()
    spotify.currently_playing()

    make_client().get_current_track()

    (call,) = spotify.calls_to(responses.POST, TOKEN_URL)
    expected = base64.b64encode(b"test-client-id:test-client-secret").decode()
    assert call.request.headers["Authorization"] == "Basic {}".format(expected)
    assert "grant_type=refresh_token" in call.request.body
    assert "refresh_token=test-refresh-token" in call.request.body


def test_access_token_is_cached_within_its_lifetime(spotify):
    spotify.token(access_token="cached-token")
    spotify.currently_playing()
    spotify.library_save()
    client = make_client()

    track = client.get_current_track()
    client.like(track.uri)
    client.get_current_track()

    assert len(spotify.calls_to(responses.POST, TOKEN_URL)) == 1
    api_calls = spotify.calls_to(responses.GET, CURRENTLY_PLAYING_URL) + spotify.calls_to(responses.PUT, LIBRARY_URL)
    assert len(api_calls) == 3
    assert all(c.request.headers["Authorization"] == "Bearer cached-token" for c in api_calls)


def test_current_track_reports_uri_title_and_first_artist(spotify):
    spotify.token()
    spotify.currently_playing()

    assert make_client().get_current_track() == CurrentTrack(
        uri="spotify:track:2fuCquhmrzHpu5xcA1ci9x", title="Under Pressure", artist="Queen"
    )


def test_like_puts_the_track_uri_to_the_library(spotify):
    spotify.token()
    spotify.library_save()

    make_client().like("spotify:track:2fuCquhmrzHpu5xcA1ci9x")

    (call,) = spotify.calls_to(responses.PUT, LIBRARY_URL)
    assert call.request.params == {"uris": "spotify:track:2fuCquhmrzHpu5xcA1ci9x"}


def refresh_tokens_sent(spotify):
    return [c.request.body for c in spotify.calls_to(responses.POST, TOKEN_URL)]


def test_a_rotated_refresh_token_is_used_for_the_next_refresh(spotify):
    # expires_in=0 makes each access token expire immediately, forcing a refresh per call.
    spotify.token(access_token="first", expires_in=0, refresh_token="rotated-refresh-token")
    spotify.token(access_token="second", expires_in=0)
    spotify.currently_playing()
    client = make_client()

    client.get_current_track()
    client.get_current_track()

    sent = refresh_tokens_sent(spotify)
    assert "refresh_token=test-refresh-token" in sent[0]
    assert "refresh_token=rotated-refresh-token" in sent[1]


def test_without_rotation_the_existing_refresh_token_keeps_being_used(spotify):
    spotify.token(expires_in=0)
    spotify.currently_playing()
    client = make_client()

    client.get_current_track()
    client.get_current_track()

    assert all("refresh_token=test-refresh-token" in body for body in refresh_tokens_sent(spotify))


@pytest.mark.parametrize("status", [400, 401])
def test_token_endpoint_rejection_raises_token_rejected(status, spotify):
    spotify.token_error(status)
    with pytest.raises(TokenRejected):
        make_client().get_current_track()


def test_api_401_raises_token_rejected_and_forces_a_fresh_token_next_time(spotify):
    spotify.token(access_token="stale")
    spotify.currently_playing(status=401)
    spotify.token(access_token="fresh")
    spotify.currently_playing()
    client = make_client()

    with pytest.raises(TokenRejected):
        client.get_current_track()
    client.get_current_track()

    assert len(spotify.calls_to(responses.POST, TOKEN_URL)) == 2


@pytest.mark.parametrize("failing_call", ["token", "currently_playing", "save"])
def test_403_raises_forbidden(failing_call, spotify):
    if failing_call == "token":
        spotify.token_error(403)
    else:
        spotify.token()
        spotify.currently_playing(status=403)
        spotify.library_save(status=403)
    client = make_client()

    with pytest.raises(Forbidden):
        if failing_call == "save":
            client.like("spotify:track:2fuCquhmrzHpu5xcA1ci9x")
        else:
            client.get_current_track()


def test_every_request_has_a_timeout(spotify):
    spotify.token()
    spotify.currently_playing()
    spotify.library_save()
    client = make_client()

    client.like(client.get_current_track().uri)

    assert len(spotify.mock.calls) == 3
    assert all(c.request.req_kwargs["timeout"] == TIMEOUT_SECONDS for c in spotify.mock.calls)
    assert TIMEOUT_SECONDS <= 3


@pytest.mark.parametrize("call", ["token", "currently_playing", "save"])
def test_failing_calls_are_not_retried(call, spotify):
    urls = {"token": (responses.POST, TOKEN_URL), "currently_playing": (responses.GET, CURRENTLY_PLAYING_URL),
            "save": (responses.PUT, LIBRARY_URL)}
    if call != "token":
        spotify.token()
    method, url = urls[call]
    spotify.fail(method, url, status=503)
    spotify.currently_playing()
    spotify.library_save()
    client = make_client()

    with pytest.raises(SpotifyUnavailable):
        if call == "save":
            client.like("spotify:track:2fuCquhmrzHpu5xcA1ci9x")
        else:
            client.get_current_track()

    assert len(spotify.calls_to(method, url)) == 1


def test_save_read_timeout_means_outcome_unknown(spotify):
    spotify.token()
    spotify.fail(responses.PUT, LIBRARY_URL, exc=requests.exceptions.ReadTimeout())

    with pytest.raises(SaveOutcomeUnknown):
        make_client().like("spotify:track:2fuCquhmrzHpu5xcA1ci9x")
