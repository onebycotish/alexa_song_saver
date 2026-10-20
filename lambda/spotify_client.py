"""Small Spotify Web API client: hides tokens, endpoints and response shapes."""
import time
from collections import namedtuple

import requests

TOKEN_URL = "https://accounts.spotify.com/api/token"
CURRENTLY_PLAYING_URL = "https://api.spotify.com/v1/me/player/currently-playing"
LIBRARY_URL = "https://api.spotify.com/v1/me/library"

# Refresh slightly early so a token never expires mid-request.
EXPIRY_MARGIN_SECONDS = 60

# Per call. Three calls in a row (token, Current Track, save) must fit inside
# Alexa's roughly 8-second response window. No retries: the Owner just asks again.
TIMEOUT_SECONDS = 3

CurrentTrack = namedtuple("CurrentTrack", ["uri", "title", "artist"])


class NothingPlaying(Exception):
    """Nothing is loaded on the Owner's Spotify account."""


class NotATrack(Exception):
    """Something is loaded, but it's an episode, ad, unknown item or local file."""


class TokenRejected(Exception):
    """Spotify won't accept the refresh token (expired, revoked or wrong)."""


class Forbidden(Exception):
    """Spotify returned 403, most likely because the Owner's Premium lapsed."""


class SpotifyUnavailable(Exception):
    """Spotify rate-limited us, errored, timed out or couldn't be reached."""


class SaveOutcomeUnknown(Exception):
    """The save or remove request was sent but no answer came back, so it may have worked."""


class SpotifyClient:
    def __init__(self, client_id, client_secret, refresh_token):
        self._auth = (client_id, client_secret)
        self._refresh_token = refresh_token
        self._access_token = None
        self._expires_at = 0.0

    def get_current_track(self):
        """Return the Current Track, playing or paused.

        Raises NothingPlaying or NotATrack when there is no Current Track.
        """
        # No additional_types: episodes then come back as a null item.
        response = self._check(self._send("GET", CURRENTLY_PLAYING_URL, headers=self._headers()))
        # The reference no longer lists 204, but the API still sends it (or an empty body).
        if response.status_code == 204 or not response.content.strip():
            raise NothingPlaying()
        body = response.json()
        item = body.get("item")
        if (
            body.get("currently_playing_type") != "track"
            or not item
            or item.get("type") != "track"
            or item.get("is_local")
        ):
            raise NotATrack()
        return CurrentTrack(uri=item["uri"], title=item["name"], artist=item["artists"][0]["name"])

    def like(self, uri):
        """Add a track to Liked Songs. Saving an already-Liked track is harmless."""
        # A read timeout means the save was sent but unanswered, so it may have worked.
        self._check(self._send("PUT", LIBRARY_URL, params={"uris": uri}, headers=self._headers(),
                               on_read_timeout=SaveOutcomeUnknown))

    def unlike(self, uri):
        """Remove a track from Liked Songs. Removing a track that isn't Liked is harmless."""
        self._check(self._send("DELETE", LIBRARY_URL, params={"uris": uri}, headers=self._headers(),
                               on_read_timeout=SaveOutcomeUnknown))

    def _check(self, response):
        if response.status_code == 401:
            # Drop the access token so the next request starts with a fresh refresh.
            self._access_token = None
            raise TokenRejected()
        if response.status_code == 403:
            raise Forbidden()
        if not response.ok:
            raise SpotifyUnavailable()
        return response

    def _send(self, method, url, on_read_timeout=SpotifyUnavailable, **kwargs):
        """Make one request with a timeout. Any network failure becomes SpotifyUnavailable."""
        try:
            return requests.request(method, url, timeout=TIMEOUT_SECONDS, **kwargs)
        except requests.exceptions.ReadTimeout:
            raise on_read_timeout()
        except requests.exceptions.RequestException:
            raise SpotifyUnavailable()

    def _headers(self):
        return {"Authorization": "Bearer {}".format(self._token())}

    def _token(self):
        if self._access_token is None or time.monotonic() >= self._expires_at:
            response = self._send(
                "POST",
                TOKEN_URL,
                data={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
                auth=self._auth,
            )
            if response.status_code in (400, 401):
                raise TokenRejected()
            if response.status_code == 403:
                raise Forbidden()
            if not response.ok:
                raise SpotifyUnavailable()
            body = response.json()
            # Spotify may rotate the refresh token. Keep the new one in memory only,
            # for the rest of this warm container's life.
            self._refresh_token = body.get("refresh_token") or self._refresh_token
            self._access_token = body["access_token"]
            self._expires_at = time.monotonic() + body["expires_in"] - EXPIRY_MARGIN_SECONDS
        return self._access_token
