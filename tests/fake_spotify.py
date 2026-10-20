"""Fakes Spotify at the network level, with response builders shaped like the real API."""
import responses

from spotify_client import CURRENTLY_PLAYING_URL, LIBRARY_URL, TOKEN_URL


def track_playing(name="Under Pressure", artists=("Queen", "David Bowie"), track_id="2fuCquhmrzHpu5xcA1ci9x",
                  is_playing=True):
    return {
        "is_playing": is_playing,
        "currently_playing_type": "track",
        "item": {
            "type": "track",
            "name": name,
            "uri": "spotify:track:{}".format(track_id),
            "is_local": False,
            "artists": [{"name": a} for a in artists],
        },
    }


def local_file():
    body = track_playing(name="My Demo", artists=["Me"])
    body["item"].update(is_local=True, uri="spotify:local:Me::My+Demo:180")
    return body


def episode():
    # Without additional_types=episode, Spotify sends a null item.
    return {"is_playing": True, "currently_playing_type": "episode", "item": None}


def ad():
    return {"is_playing": True, "currently_playing_type": "ad", "item": None}


def unknown():
    return {"is_playing": True, "currently_playing_type": "unknown", "item": None}


class FakeSpotify:
    def __init__(self, mock):
        self.mock = mock

    def token(self, access_token="test-access-token", expires_in=3600, **extra):
        self.mock.add(responses.POST, TOKEN_URL,
                      json=dict(access_token=access_token, token_type="Bearer", expires_in=expires_in, **extra))

    def token_error(self, status=400):
        self.mock.add(responses.POST, TOKEN_URL, status=status,
                      json={"error": "invalid_grant", "error_description": "Invalid refresh token"})

    def currently_playing(self, body=None, status=200):
        if status != 200:
            self.mock.add(responses.GET, CURRENTLY_PLAYING_URL, status=status,
                          json={"error": {"status": status, "message": "error"}})
            return
        self.mock.add(responses.GET, CURRENTLY_PLAYING_URL, json=body if body is not None else track_playing())

    def nothing_playing(self, status=204):
        self.mock.add(responses.GET, CURRENTLY_PLAYING_URL, status=status, body="")

    def library_save(self, status=200):
        self.mock.add(responses.PUT, LIBRARY_URL, status=status)

    def library_remove(self, status=200):
        self.mock.add(responses.DELETE, LIBRARY_URL, status=status)

    def fail(self, method, url, status=None, exc=None):
        """Make one call fail with an HTTP status or a network exception (e.g. a timeout)."""
        if exc is not None:
            self.mock.add(method, url, body=exc)
        else:
            self.mock.add(method, url, status=status, json={"error": {"status": status, "message": "error"}})

    def calls_to(self, method, url):
        return [c for c in self.mock.calls if c.request.method == method and c.request.url.split("?")[0] == url]
