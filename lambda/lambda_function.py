"""Alexa entry point for Song Saver.

Every response ends the session so the Owner's music resumes straight away.
"""
import datetime
import logging
from xml.sax.saxutils import escape

from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import is_intent_name, is_request_type

from config import ConfigError, load_config
from spotify_client import (
    Forbidden,
    NotATrack,
    NothingPlaying,
    SaveOutcomeUnknown,
    SpotifyClient,
    SpotifyUnavailable,
    TokenRejected,
)

LIKE_INTENT = "LikeSongIntent"
UNLIKE_INTENT = "UnlikeSongIntent"
HELP_INTENTS = ("AMAZON.HelpIntent", "AMAZON.FallbackIntent")
QUIET_INTENTS = ("AMAZON.StopIntent", "AMAZON.CancelIntent", "AMAZON.NavigateHomeIntent")

# Every intent the handlers serve; must match the interaction model exactly.
HANDLED_INTENTS = (LIKE_INTENT, UNLIKE_INTENT) + HELP_INTENTS + QUIET_INTENTS

HELP_TEXT = "Say 'Alexa, ask song saver to like this song' or 'remove this song', or just 'Alexa, open song saver'."
SAVED_TEXT = "Saved {title} by {artist} to your Liked Songs."
REMOVED_TEXT = "Removed {title} by {artist} from your Liked Songs."
NOT_SET_UP_TEXT = "Song Saver isn't set up yet. Check secrets.json."
NOTHING_PLAYING_TEXT = "I don't see anything playing on Spotify right now."
NOT_A_TRACK_TEXT = "That isn't a song I can change in your Liked Songs."
AUTHORIZATION_EXPIRED_TEXT = "Your Spotify authorization has expired. Run the refresh token script again."
TOKEN_REJECTED_TEXT = "Spotify rejected your refresh token. Check secrets.json, or run the refresh token script again."
FORBIDDEN_TEXT = "Spotify refused the request. Check that your account still has Premium."
UNAVAILABLE_TEXT = "Spotify isn't responding right now. Try again in a moment."
NOT_SURE_SAVED_TEXT = "I'm not sure that saved. Check your Liked Songs."
NOT_SURE_REMOVED_TEXT = "I'm not sure that was removed. Check your Liked Songs."

# Spotify refresh tokens last six months from Authorization; refreshing doesn't extend them.
AUTHORIZATION_LIFETIME = datetime.timedelta(days=180)

logger = logging.getLogger(__name__)

sb = SkillBuilder()

# Reused across warm invocations so the access token stays cached. Replaced
# when secrets.json changes, e.g. after the Owner re-runs the token script.
_client = None
_client_key = None


def _spotify(config):
    global _client, _client_key
    key = (config.client_id, config.client_secret, config.refresh_token)
    if key != _client_key:
        _client = SpotifyClient(*key)
        _client_key = key
    return _client


def _ssml_text(text):
    return escape(text, {'"': "&quot;", "'": "&apos;"})


def _any_intent(names):
    return lambda handler_input: any(is_intent_name(n)(handler_input) for n in names)


def _end(handler_input, speech=None):
    builder = handler_input.response_builder
    if speech:
        builder.speak(speech)
    return builder.set_should_end_session(True).response


@sb.request_handler(
    can_handle_func=lambda hi: is_request_type("LaunchRequest")(hi) or is_intent_name(LIKE_INTENT)(hi)
)
def like_handler(handler_input):
    return _change_current_track(handler_input, SpotifyClient.like, SAVED_TEXT, NOT_SURE_SAVED_TEXT)


@sb.request_handler(can_handle_func=is_intent_name(UNLIKE_INTENT))
def unlike_handler(handler_input):
    return _change_current_track(handler_input, SpotifyClient.unlike, REMOVED_TEXT, NOT_SURE_REMOVED_TEXT)


def _change_current_track(handler_input, change, done_text, not_sure_text):
    try:
        config = load_config()
    except ConfigError as e:
        logger.warning("Not set up: %s", e)
        return _end(handler_input, NOT_SET_UP_TEXT)
    try:
        speech = _apply_to_current_track(_spotify(config), change, done_text)
    except TokenRejected:
        speech = AUTHORIZATION_EXPIRED_TEXT if _authorization_lapsed(config) else TOKEN_REJECTED_TEXT
    except Forbidden:
        speech = FORBIDDEN_TEXT
    except SpotifyUnavailable:
        speech = UNAVAILABLE_TEXT
    except SaveOutcomeUnknown:
        speech = not_sure_text
    return _end(handler_input, speech)


def _apply_to_current_track(spotify, change, done_text):
    try:
        track = spotify.get_current_track()
    except NothingPlaying:
        return NOTHING_PLAYING_TEXT
    except NotATrack:
        return NOT_A_TRACK_TEXT
    change(spotify, track.uri)
    return done_text.format(title=_ssml_text(track.title), artist=_ssml_text(track.artist))


def _authorization_lapsed(config):
    return datetime.date.today() - config.authorized_at >= AUTHORIZATION_LIFETIME


@sb.request_handler(can_handle_func=_any_intent(HELP_INTENTS))
def help_handler(handler_input):
    # Fallback deliberately never Likes or Unlikes: a misheard phrase must not change Liked Songs.
    return _end(handler_input, HELP_TEXT)


@sb.request_handler(can_handle_func=_any_intent(QUIET_INTENTS))
def quiet_handler(handler_input):
    return _end(handler_input)


@sb.request_handler(can_handle_func=is_request_type("SessionEndedRequest"))
def session_ended_handler(handler_input):
    return _end(handler_input)


@sb.exception_handler(can_handle_func=lambda handler_input, exception: True)
def unexpected_error_handler(handler_input, exception):
    # Never let Alexa play its generic "problem with the requested skill's response".
    logger.exception("Unexpected error: %s", exception)
    return _end(handler_input, UNAVAILABLE_TEXT)


lambda_handler = sb.lambda_handler()
