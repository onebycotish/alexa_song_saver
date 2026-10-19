"""One-time Spotify Authorization for Song Saver.

Reads client_id and client_secret from lambda/secrets.json, opens Spotify's
consent page, catches the callback on http://127.0.0.1:8888/callback, and writes
refresh_token and authorized_at back into the same file, keeping every other key.

Run it again whenever the Authorization lapses (every six months).

    python scripts/get_refresh_token.py [--secrets PATH]
"""
import argparse
import datetime
import json
import os
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
HOST, PORT = "127.0.0.1", 8888
REDIRECT_URI = "http://{}:{}/callback".format(HOST, PORT)
SCOPES = "user-read-currently-playing user-library-modify"

DEFAULT_SECRETS = Path(__file__).resolve().parent.parent / "lambda" / "secrets.json"
PLACEHOLDER_PREFIXES = ("YOUR_", "FILLED_IN_")


class SetupError(Exception):
    pass


def read_secrets(path):
    if not path.exists():
        raise SetupError(
            "{} not found. Copy lambda/secrets.example.json to lambda/secrets.json "
            "and fill in client_id and client_secret.".format(path)
        )
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        raise SetupError("{} isn't valid JSON: {}".format(path, e))
    if not isinstance(data, dict):
        raise SetupError("{} must contain a JSON object.".format(path))
    for key in ("client_id", "client_secret"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or value.startswith(PLACEHOLDER_PREFIXES):
            raise SetupError("Fill in {} in {} from your Spotify developer dashboard.".format(key, path))
    return data


def wait_for_callback(state):
    """Serve until Spotify redirects back; return the authorization code."""
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            params = {k: v[0] for k, v in parse_qs(url.query).items()}
            if params.get("state") != state:
                result["error"] = "state mismatch (the callback didn't come from this run)"
            elif "error" in params:
                result["error"] = params["error"]
            elif "code" in params:
                result["code"] = params["code"]
            else:
                result["error"] = "no code in callback"
            ok = "code" in result
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            message = "Song Saver is authorized. You can close this tab." if ok else "Authorization failed. See the terminal."
            self.wfile.write(message.encode())

        def log_message(self, *args):
            pass

    server = HTTPServer((HOST, PORT), Handler)
    try:
        while not result:
            server.handle_request()
    finally:
        server.server_close()
    if "error" in result:
        raise SetupError("Spotify authorization failed: {}".format(result["error"]))
    return result["code"]


def exchange_code(code, client_id, client_secret):
    response = requests.post(
        TOKEN_URL,
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
        auth=(client_id, client_secret),
        timeout=10,
    )
    if not response.ok:
        raise SetupError("Token exchange failed ({}): {}".format(response.status_code, response.text))
    refresh_token = response.json().get("refresh_token")
    if not refresh_token:
        raise SetupError("Spotify's response had no refresh_token.")
    return refresh_token


def write_secrets(path, data):
    # Write to a temp file first so a crash can't leave secrets.json half-written.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(str(tmp), str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--secrets", type=Path, default=DEFAULT_SECRETS, help="path to secrets.json")
    args = parser.parse_args(argv)

    try:
        data = read_secrets(args.secrets)
        state = secrets.token_urlsafe(16)
        url = "{}?{}".format(AUTHORIZE_URL, urlencode({
            "client_id": data["client_id"],
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
        }))
        print("Opening Spotify in your browser. If it doesn't open, visit:\n\n  {}\n".format(url))
        webbrowser.open(url)
        code = wait_for_callback(state)
        data["refresh_token"] = exchange_code(code, data["client_id"], data["client_secret"])
        data["authorized_at"] = datetime.date.today().isoformat()
        write_secrets(args.secrets, data)
    except SetupError as e:
        print("Error: {}".format(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. Nothing was written.", file=sys.stderr)
        return 1

    print("Done. Saved refresh_token and authorized_at ({}) to {}.".format(data["authorized_at"], args.secrets))
    print("Re-run this script before {} to renew the Authorization.".format(
        datetime.date.today() + datetime.timedelta(days=180)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
