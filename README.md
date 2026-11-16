# F1 Session Viewer

Browse historical Formula 1 race results and lap times, powered by the free [OpenF1 API](https://openf1.org).
A small Flask app: Jinja templates, a sprinkle of vanilla JavaScript, no build step.

## Run it

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app app run --debug
```

Then open http://127.0.0.1:5000.

On Debian/Ubuntu you may first need `sudo apt install python3-venv`.

## What's in here

```
app.py             routes, OpenF1 client (with retries + caching), auth flow, predictions
auth.py            password policy, in-memory accounts, TOTP enrolment/verification
templates/         Jinja pages (_ui.html holds the shared buttons, inputs, badges)
static/            style.css and one small script per page
requirements.txt   Flask, requests, segno (QR codes)
```

## Authentication

Accounts live in memory for now, so they disappear when the server restarts. Passwords are compared
as-is; persistence and password hashing are the next step (the call sites are already separated in
`auth.py`). Every account must enrol a TOTP authenticator before it is created — **Microsoft
Authenticator** works out of the box: scan the QR code shown at sign-up, or type the displayed key
into the app manually. Signing in then requires the current 6-digit code.

Password policy:

- Length (NIST SP 800-63B): at least **8 characters** with two-factor authentication enabled (the
  normal sign-up path), **15** without it, and up to **128**.
- Composition: at least one uppercase letter, one lowercase letter and one number. **No symbol is
  required**, and no characters are disallowed — `#`, spaces, etc. are all fine.
- The password can't contain your email address, can't be only spaces, and a short list of common
  passwords is refused. The sign-up form shows a live checklist for the composition rules.

Failed codes and passwords are throttled: five failures lock the account for five minutes, and a
TOTP code can't be replayed. Codes are accepted with one 30-second step of clock drift. An unfinished
sign-up lives only in server memory for ten minutes, so restarting the server means starting
enrolment again.

## Notes

- **Set `SECRET_KEY`** in the environment for anything beyond local use; it signs the session
  cookie. Behind HTTPS, also set `SESSION_COOKIE_SECURE=1`.
- **Needs internet.** Tailwind CSS, Chart.js and the fonts load from CDNs, and race data comes from OpenF1.
- OpenF1 is rate limited. The server retries on `429` and caches responses, so revisiting a race is instant.
