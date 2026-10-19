# Song Saver

**Like the song that's playing on Spotify, by talking to your Echo.**

![Python 3.8](https://img.shields.io/badge/python-3.8-3776AB?logo=python&logoColor=white)
![Alexa-hosted](https://img.shields.io/badge/Alexa-hosted-00CAFF?logo=amazonalexa&logoColor=white)
![MIT licence](https://img.shields.io/badge/licence-MIT-lightgrey)

> **You:** Alexa, ask song saver to like this song.
>
> **Alexa:** Saved Under Pressure by Queen to your Liked Songs.

Alexa's built-in Spotify integration can play, pause and skip, but it can't add a song to Liked Songs. Song Saver adds that one missing command.

It's a personal skill. You deploy your own private copy with your own Spotify developer app, and it runs only on your devices. There's no account linking and no store listing.

---

## What you need

- **Spotify Premium.** Spotify developer apps in Development Mode only work while the app owner has Premium.
- **An Amazon developer account** on the same Amazon account as your Echo.
- **An Echo set to English (US) or English (India).** Check this in the Alexa app under **Devices → your Echo → Language**.
- **Python 3.8+** on your computer, for the one-time setup script.

---

## Setup

About 20 minutes, done once. Run the commands in **Terminal**.

### 1. Get the code

```sh
git clone https://github.com/onebycotish/alexa_song_saver.git
cd alexa_song_saver
```

### 2. Create a Spotify app

1. Create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and tick **Web API**.
2. Add this redirect URI exactly: `http://127.0.0.1:8888/callback`
3. In the app's **Settings**, note the **Client ID** and **Client Secret**.

### 3. Connect it to your Spotify account

Make your secrets file from the template, then open it:

```sh
cp lambda/secrets.example.json lambda/secrets.json
open -e lambda/secrets.json
```

Replace `YOUR_SPOTIFY_CLIENT_ID` and `YOUR_SPOTIFY_CLIENT_SECRET` with your values, keeping the quotes. Leave the other two lines alone and save.

Then run the Authorization script:

```sh
python3 -m venv .venv
.venv/bin/pip install -r lambda/requirements.txt
.venv/bin/python scripts/get_refresh_token.py
```

Approve the Spotify page that opens in your browser. The script fills in the rest of `lambda/secrets.json` for you.

> [!NOTE]
> Skip the first two commands if you already have a `.venv` folder.
> `lambda/secrets.json` is gitignored. Never commit it.

### 4. Set up the skill in Alexa

In the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask), create a **Custom** skill with the **Alexa-hosted (Python)** backend and the languages English (US) and English (IN). Then fill in three tabs:

**Build**: for each language, open **Interaction Model → JSON Editor**, paste in the matching file, click **Save**, then **Build skill**.

| Language | File |
|---|---|
| English (US) | `skill-package/interactionModels/custom/en-US.json` |
| English (IN) | `skill-package/interactionModels/custom/en-IN.json` |

**Code**: make the `lambda` folder match this repo's:

```
lambda/
├── config.py           create, paste
├── lambda_function.py  replace
├── requirements.txt    replace
├── secrets.json        create as lambda/secrets.json
└── spotify_client.py   create, paste
```

Delete the template's `utils.py` if it's there, then click **Save** and **Deploy**.

> [!IMPORTANT]
> When you create the secrets file, type the full path `lambda/secrets.json`. If you type just `secrets.json`, the file lands outside the folder, doesn't get deployed, and Alexa says "Song Saver isn't set up yet."
> Copy it with `cat lambda/secrets.json | pbcopy` so the quotes stay intact.

**Test**: set **Skill testing is enabled in** to **Development**. Leave it on. That setting is what lets your Echo use the skill.

### 5. Try it

Play something on Spotify, then say any of:

- *"Alexa, open song saver"*
- *"Alexa, ask song saver to like this song"*
- *"Alexa, ask song saver to save this"*
- *"Alexa, ask song saver to add this to my liked songs"*

The song appears in **Liked Songs**. You can now close the console. The skill keeps working.

---

## How it behaves

- **It Likes whatever is loaded right now, playing or paused.** Alexa often pauses the music while it listens.
- **It names the song it saved,** so you'll notice if the track changed mid-sentence. Remove a wrong one in the Spotify app.
- **It ends straight away,** so your music carries on.
- **Saving an already-Liked song does no harm.** There's no "unlike" by voice.

## Every six months: renew your Authorization

Spotify's Authorization expires six months after you grant it. When Alexa says *"Your Spotify authorization has expired"*:

1. Run `.venv/bin/python scripts/get_refresh_token.py`. It prints your next renewal date.
2. Paste the updated `lambda/secrets.json` into the console's **Code** tab.
3. Click **Deploy**.

---

## Troubleshooting

| Alexa says | Fix |
|---|---|
| *"Song Saver isn't set up yet."* | `secrets.json` is missing from the console's `lambda` folder, or still has placeholder values. See step 4. |
| *"I don't see anything playing on Spotify right now."* | Start something in Spotify first. |
| *"That isn't something I can add to your Liked Songs."* | Podcasts, ads and local files can't be Liked. |
| *"Your Spotify authorization has expired."* | [Renew it](#every-six-months-renew-your-authorization). |
| *"Spotify rejected your refresh token…"* | Make sure the console's `secrets.json` matches yours, or run the script again. |
| *"Spotify refused the request…"* | Check your Premium is active, and that your account is listed under the Spotify app's **User Management**. |
| *"Spotify isn't responding right now."* | Spotify was slow or down. Ask again. |
| *"I'm not sure that saved."* | Check Liked Songs, and ask again if it's missing. |
| *"You just triggered LikeSongIntent."* | Amazon's starter code is still running. Redo **Code** in step 4 and **Deploy**. |
| *"There was a problem with the requested skill's response."* | Read the error in **Code → CloudWatch Logs → Logs → Log groups**. For India and Europe, the logs are in the **Europe (Ireland)** region. |

If "open song saver" isn't recognised at all, check your Echo's language and that testing is set to **Development**.

---

## Development

The code targets **Python 3.8**, the only Python runtime Alexa-hosted skills offer. Run the tests on that version:

```sh
uv python install 3.8
uv venv --python 3.8 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest
```

The tests fake Spotify at the network level and use a temporary secrets file, so they never touch your real account or `secrets.json`.

| Path | What it is |
|---|---|
| `lambda/lambda_function.py` | Alexa handlers and every spoken reply |
| `lambda/spotify_client.py` | Tokens, the current track, saving to Liked Songs |
| `lambda/config.py` | Loads `secrets.json` |
| `scripts/get_refresh_token.py` | One-time Spotify Authorization |
| `skill-package/` | Interaction models for both languages |
| `tests/` | pytest suite |

## Licence

[MIT](LICENSE)
