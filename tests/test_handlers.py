import datetime

import pytest
import requests
import responses

import alexa_requests as req
from conftest import VALID_SECRETS
import fake_spotify
from fake_spotify import track_playing
from lambda_function import (
    AUTHORIZATION_EXPIRED_TEXT,
    FORBIDDEN_TEXT,
    HELP_TEXT,
    NOT_A_TRACK_TEXT,
    NOT_SET_UP_TEXT,
    NOTHING_PLAYING_TEXT,
    NOT_SURE_REMOVED_TEXT,
    NOT_SURE_SAVED_TEXT,
    TOKEN_REJECTED_TEXT,
    UNAVAILABLE_TEXT,
    lambda_handler,
)
from spotify_client import CURRENTLY_PLAYING_URL, LIBRARY_URL, TOKEN_URL


def invoke(envelope):
    return lambda_handler(envelope, None)["response"]


def speech(response):
    return response.get("outputSpeech", {}).get("ssml")


def ssml(text):
    return "<speak>{}</speak>".format(text)


LIKE_REQUESTS = [req.launch(), req.intent("LikeSongIntent")]
UNLIKE_REQUEST = req.intent("UnlikeSongIntent")
CHANGE_REQUESTS = LIKE_REQUESTS + [UNLIKE_REQUEST]
HELP_REQUESTS = [req.intent("AMAZON.HelpIntent"), req.intent("AMAZON.FallbackIntent")]
QUIET_REQUESTS = [
    req.intent("AMAZON.StopIntent"),
    req.intent("AMAZON.CancelIntent"),
    req.intent("AMAZON.NavigateHomeIntent"),
    req.session_ended(),
]


# --- Liking the Current Track ---

@pytest.mark.parametrize("envelope", LIKE_REQUESTS)
def test_like_saves_the_current_track_and_names_title_and_first_artist(envelope, valid_secrets, spotify_ok):
    response = invoke(envelope)

    assert speech(response) == ssml("Saved Under Pressure by Queen to your Liked Songs.")
    saves = spotify_ok.calls_to(responses.PUT, LIBRARY_URL)
    assert len(saves) == 1
    assert saves[0].request.params == {"uris": "spotify:track:2fuCquhmrzHpu5xcA1ci9x"}


def test_a_paused_track_is_still_liked(valid_secrets, spotify):
    spotify.token()
    spotify.currently_playing(track_playing(is_playing=False))
    spotify.library_save()

    assert speech(invoke(req.launch())) == ssml("Saved Under Pressure by Queen to your Liked Songs.")
    assert len(spotify.calls_to(responses.PUT, LIBRARY_URL)) == 1


def test_title_is_spoken_exactly_as_spotify_gives_it(valid_secrets, spotify):
    spotify.token()
    spotify.currently_playing(track_playing(name="Here Comes the Sun - Remastered 2009", artists=["The Beatles"]))
    spotify.library_save()

    assert speech(invoke(req.launch())) == ssml(
        "Saved Here Comes the Sun - Remastered 2009 by The Beatles to your Liked Songs."
    )


def test_special_characters_are_escaped_for_ssml(valid_secrets, spotify):
    spotify.token()
    spotify.currently_playing(track_playing(name='Rock & Roll <Live> "Take 2"', artists=["Simon & Garfunkel's Band"]))
    spotify.library_save()

    assert speech(invoke(req.launch())) == ssml(
        "Saved Rock &amp; Roll &lt;Live&gt; &quot;Take 2&quot; "
        "by Simon &amp; Garfunkel&apos;s Band to your Liked Songs."
    )


@pytest.mark.parametrize("envelope", CHANGE_REQUESTS)
def test_no_already_saved_check_is_made(envelope, valid_secrets, spotify_ok):
    invoke(envelope)
    assert not [c for c in spotify_ok.mock.calls if "/me/library/contains" in c.request.url]


@pytest.mark.parametrize("envelope", LIKE_REQUESTS)
def test_like_never_removes(envelope, valid_secrets, spotify_ok):
    invoke(envelope)
    assert not spotify_ok.calls_to(responses.DELETE, LIBRARY_URL)


# --- Unliking the Current Track ---

@pytest.mark.parametrize("is_playing", [True, False], ids=["playing", "paused"])
def test_unlike_removes_the_current_track_and_names_it(is_playing, valid_secrets, spotify):
    spotify.token()
    spotify.currently_playing(track_playing(name="Rock & Roll", is_playing=is_playing))
    spotify.library_remove()

    response = invoke(UNLIKE_REQUEST)

    assert speech(response) == ssml("Removed Rock &amp; Roll by Queen from your Liked Songs.")
    assert response["shouldEndSession"] is True
    (call,) = spotify.calls_to(responses.DELETE, LIBRARY_URL)
    assert call.request.params == {"uris": "spotify:track:2fuCquhmrzHpu5xcA1ci9x"}
    assert not spotify.calls_to(responses.PUT, LIBRARY_URL)


@pytest.mark.parametrize("failure, expected", [
    pytest.param(dict(status=401), TOKEN_REJECTED_TEXT, id="401"),
    pytest.param(dict(status=403), FORBIDDEN_TEXT, id="403"),
    pytest.param(dict(status=500), UNAVAILABLE_TEXT, id="500"),
    pytest.param(dict(exc=requests.exceptions.ConnectionError()), UNAVAILABLE_TEXT, id="connection-error"),
    pytest.param(dict(exc=requests.exceptions.ReadTimeout()), NOT_SURE_REMOVED_TEXT, id="read-timeout-may-have-removed"),
])
def test_remove_failure_replies(failure, expected, valid_secrets, spotify):
    spotify.token()
    spotify.currently_playing()
    spotify.fail(responses.DELETE, LIBRARY_URL, **failure)

    response = invoke(UNLIKE_REQUEST)

    assert speech(response) == ssml(expected)
    assert response["shouldEndSession"] is True


# --- Things that can't be Liked or Unliked ---

def library_writes(spotify):
    return spotify.calls_to(responses.PUT, LIBRARY_URL) + spotify.calls_to(responses.DELETE, LIBRARY_URL)


@pytest.mark.parametrize("status", [204, 200], ids=["204", "empty-200"])
@pytest.mark.parametrize("envelope", CHANGE_REQUESTS)
def test_nothing_playing(envelope, status, valid_secrets, spotify):
    spotify.token()
    spotify.nothing_playing(status=status)

    response = invoke(envelope)

    assert speech(response) == ssml(NOTHING_PLAYING_TEXT)
    assert response["shouldEndSession"] is True
    assert not library_writes(spotify)


@pytest.mark.parametrize("body", [
    pytest.param(fake_spotify.episode(), id="episode"),
    pytest.param(fake_spotify.ad(), id="ad"),
    pytest.param(fake_spotify.unknown(), id="unknown"),
    pytest.param(fake_spotify.local_file(), id="local-file"),
])
@pytest.mark.parametrize("envelope", CHANGE_REQUESTS)
def test_not_a_track(envelope, body, valid_secrets, spotify):
    spotify.token()
    spotify.currently_playing(body)

    response = invoke(envelope)

    assert speech(response) == ssml(NOT_A_TRACK_TEXT)
    assert response["shouldEndSession"] is True
    assert not library_writes(spotify)


def test_currently_playing_request_does_not_ask_for_episodes(valid_secrets, spotify_ok):
    invoke(req.launch())
    (call,) = spotify_ok.calls_to(responses.GET, fake_spotify.CURRENTLY_PLAYING_URL)
    assert "additional_types" not in call.request.url


# --- Token and Authorization problems ---

def days_ago(n):
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


@pytest.mark.parametrize("status", [400, 401])
@pytest.mark.parametrize("authorized_days_ago, expected", [
    pytest.param(200, AUTHORIZATION_EXPIRED_TEXT, id="lapsed"),
    pytest.param(180, AUTHORIZATION_EXPIRED_TEXT, id="just-lapsed"),
    pytest.param(179, TOKEN_REJECTED_TEXT, id="almost-lapsed"),
    pytest.param(10, TOKEN_REJECTED_TEXT, id="recent"),
])
def test_rejected_token_reply_depends_on_authorization_age(status, authorized_days_ago, expected, write_secrets,
                                                           spotify):
    write_secrets(authorized_at=days_ago(authorized_days_ago))
    spotify.token_error(status)

    response = invoke(req.launch())

    assert speech(response) == ssml(expected)
    assert response["shouldEndSession"] is True


def test_api_401_is_a_rejected_token(valid_secrets, spotify):
    spotify.token()
    spotify.currently_playing(status=401)

    assert speech(invoke(req.launch())) == ssml(TOKEN_REJECTED_TEXT)


@pytest.mark.parametrize("failing_call", ["token", "currently_playing", "save"])
def test_403_asks_the_owner_to_check_premium(failing_call, valid_secrets, spotify):
    if failing_call == "token":
        spotify.token_error(403)
    else:
        spotify.token()
        spotify.currently_playing(status=403 if failing_call == "currently_playing" else 200)
        spotify.library_save(status=403)

    response = invoke(req.launch())

    assert speech(response) == ssml(FORBIDDEN_TEXT)
    assert response["shouldEndSession"] is True


def test_skill_never_writes_the_secrets_file(valid_secrets, secrets_path, spotify):
    before = secrets_path.read_text()
    spotify.token(refresh_token="rotated-refresh-token")
    spotify.currently_playing()
    spotify.library_save()

    invoke(req.launch())

    assert secrets_path.read_text() == before


# --- Spotify not responding ---

FAILURES = [
    pytest.param(dict(status=429), id="429"),
    pytest.param(dict(status=500), id="500"),
    pytest.param(dict(status=503), id="503"),
    pytest.param(dict(exc=requests.exceptions.ReadTimeout()), id="read-timeout"),
    pytest.param(dict(exc=requests.exceptions.ConnectTimeout()), id="connect-timeout"),
    pytest.param(dict(exc=requests.exceptions.ConnectionError()), id="connection-error"),
]


@pytest.mark.parametrize("failure", FAILURES)
def test_token_failure_says_spotify_isnt_responding(failure, valid_secrets, spotify):
    spotify.fail(responses.POST, TOKEN_URL, **failure)

    response = invoke(req.launch())

    assert speech(response) == ssml(UNAVAILABLE_TEXT)
    assert response["shouldEndSession"] is True


@pytest.mark.parametrize("failure", FAILURES)
def test_current_track_failure_says_spotify_isnt_responding(failure, valid_secrets, spotify):
    spotify.token()
    spotify.fail(responses.GET, CURRENTLY_PLAYING_URL, **failure)

    assert speech(invoke(req.launch())) == ssml(UNAVAILABLE_TEXT)
    assert not spotify.calls_to(responses.PUT, LIBRARY_URL)


@pytest.mark.parametrize("failure, expected", [
    pytest.param(dict(status=429), UNAVAILABLE_TEXT, id="429"),
    pytest.param(dict(status=500), UNAVAILABLE_TEXT, id="500"),
    pytest.param(dict(exc=requests.exceptions.ConnectTimeout()), UNAVAILABLE_TEXT, id="connect-timeout-never-sent"),
    pytest.param(dict(exc=requests.exceptions.ConnectionError()), UNAVAILABLE_TEXT, id="connection-error"),
    pytest.param(dict(exc=requests.exceptions.ReadTimeout()), NOT_SURE_SAVED_TEXT, id="read-timeout-may-have-saved"),
])
def test_save_failure_replies(failure, expected, valid_secrets, spotify):
    spotify.token()
    spotify.currently_playing()
    spotify.fail(responses.PUT, LIBRARY_URL, **failure)

    response = invoke(req.launch())

    assert speech(response) == ssml(expected)
    assert response["shouldEndSession"] is True


def test_an_unexpected_error_still_gets_a_spoken_reply(valid_secrets, spotify):
    malformed = track_playing()
    del malformed["item"]["artists"]
    spotify.token()
    spotify.currently_playing(malformed)

    response = invoke(req.launch())

    assert speech(response) == ssml(UNAVAILABLE_TEXT)
    assert response["shouldEndSession"] is True


# --- Not set up ---

def _without(key):
    return {k: v for k, v in VALID_SECRETS.items() if k != key}


BROKEN_SECRETS = [
    pytest.param(None, id="missing-file"),
    pytest.param("{not json", id="invalid-json"),
    pytest.param("[]", id="not-an-object"),
    pytest.param(_without("client_id"), id="missing-client-id"),
    pytest.param(_without("client_secret"), id="missing-client-secret"),
    pytest.param(_without("refresh_token"), id="missing-refresh-token"),
    pytest.param(_without("authorized_at"), id="missing-authorized-at"),
    pytest.param(dict(VALID_SECRETS, refresh_token="  "), id="blank-value"),
    pytest.param(dict(VALID_SECRETS, authorized_at="FILLED_IN_BY_GET_REFRESH_TOKEN_SCRIPT"), id="script-not-run"),
]


@pytest.mark.parametrize("secrets", BROKEN_SECRETS)
@pytest.mark.parametrize("envelope", CHANGE_REQUESTS)
def test_like_says_not_set_up_when_secrets_are_broken(envelope, secrets, write_secrets, spotify):
    if secrets is not None:
        write_secrets(secrets)
    response = invoke(envelope)
    assert speech(response) == ssml(NOT_SET_UP_TEXT)
    assert response["shouldEndSession"] is True
    assert not spotify.mock.calls


# --- Help, Fallback and quiet intents ---
# These run with no secrets file (see conftest), proving they work before setup.

@pytest.mark.parametrize("envelope", HELP_REQUESTS)
def test_help_and_fallback_speak_one_help_sentence(envelope):
    assert speech(invoke(envelope)) == ssml(HELP_TEXT)


def test_help_mentions_removing():
    assert "remove this song" in HELP_TEXT


def test_fallback_never_calls_spotify(valid_secrets, spotify):
    invoke(req.intent("AMAZON.FallbackIntent"))
    assert not spotify.mock.calls


@pytest.mark.parametrize("envelope", QUIET_REQUESTS)
def test_stop_cancel_and_session_end_are_silent(envelope):
    assert speech(invoke(envelope)) is None


@pytest.mark.parametrize("envelope", CHANGE_REQUESTS + HELP_REQUESTS + QUIET_REQUESTS)
def test_every_response_ends_the_session(envelope, valid_secrets, spotify_ok):
    assert invoke(envelope)["shouldEndSession"] is True
