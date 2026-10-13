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
app.py             routes, OpenF1 client (with retries + caching), demo auth, predictions
templates/         Jinja pages (_ui.html holds the shared buttons, inputs, badges)
static/            style.css and one small script per page
requirements.txt   Flask, requests
```

## Notes

- **Auth is a demo.** Any well-formed email/password and any 6-digit code signs you in; nothing is stored
  except a signed session cookie. Predictions are sample data plus your Singapore pick for the current session.
  Set `SECRET_KEY` in the environment for anything beyond local use.
- **Needs internet.** Tailwind CSS, Chart.js and the fonts load from CDNs, and race data comes from OpenF1.
- OpenF1 is rate limited. The server retries on `429` and caches responses, so revisiting a race is instant.
