import os
import re
import time
from functools import wraps

import requests
from flask import Flask, abort, jsonify, make_response, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-secret-change-me")

OPENF1 = "https://api.openf1.org/v1"
YEARS = ["2025", "2024", "2023", "2022"]


# ── OpenF1 client ─────────────────────────────────────────────────────────────

class OpenF1Error(Exception):
    pass


_cache = {}  # historical data never changes, so cache every response


def openf1(path, retries=3, delay=0.8, **params):
    key = (path, tuple(sorted(params.items())))
    if key in _cache:
        return _cache[key]

    for attempt in range(retries + 1):
        try:
            res = requests.get(f"{OPENF1}{path}", params=params, timeout=20)
        except requests.RequestException:
            raise OpenF1Error("Could not reach OpenF1. Check your connection and try again.")
        if res.status_code == 429:
            if attempt == retries:
                raise OpenF1Error("Rate limit reached — please wait a moment and try again.")
            time.sleep(delay * 2 ** attempt)
            continue
        if res.status_code == 404:  # OpenF1 answers 404 when a query matches nothing
            _cache[key] = []
            return []
        if not res.ok:
            raise OpenF1Error(f"OpenF1 {res.status_code}: {res.reason}")
        _cache[key] = res.json()
        return _cache[key]
    raise OpenF1Error("Request failed after retries.")


def get_meetings(year):
    return sorted(openf1("/meetings", year=year), key=lambda m: m["meeting_key"])


def get_race_session(meeting_key):
    sessions = openf1("/sessions", meeting_key=meeting_key, session_name="Race")
    return sessions[0] if sessions else None


_results_cache = {}


def get_results(session_key):
    """Final classification, plus best laps and lap-time series for the top 5."""
    if session_key in _results_cache:
        return _results_cache[session_key]

    drivers = openf1("/drivers", session_key=session_key)
    positions = {e["driver_number"]: e["position"] for e in openf1("/position", session_key=session_key)}

    rows = sorted(
        ({**d, "position": positions[d["driver_number"]], "best_lap": None}
         for d in drivers if d["driver_number"] in positions),
        key=lambda r: r["position"],
    )

    # Laps only for the top 5, one request at a time to stay under the rate limit
    top5 = rows[:5]
    laps_by_driver = {}
    for i, row in enumerate(top5):
        if i:
            time.sleep(0.4)
        laps = openf1("/laps", session_key=session_key, driver_number=row["driver_number"])
        laps_by_driver[row["driver_number"]] = {
            lap["lap_number"]: lap["lap_duration"]
            for lap in laps
            if lap["lap_number"] and lap["lap_duration"] and lap["lap_duration"] > 0
        }
        row["best_lap"] = min(laps_by_driver[row["driver_number"]].values(), default=None)

    lap_numbers = sorted({n for laps in laps_by_driver.values() for n in laps})
    data = {
        "rows": [
            {
                "position": r["position"],
                "driver_number": r["driver_number"],
                "full_name": r["full_name"],
                "team_name": r["team_name"],
                "team_colour": r["team_colour"] or "",
                "best_lap": r["best_lap"],
            }
            for r in rows
        ],
        "chart": {
            "laps": lap_numbers,
            "drivers": [
                {
                    "acronym": r["name_acronym"],
                    "colour": r["team_colour"] or "",
                    "times": [laps_by_driver[r["driver_number"]].get(n) for n in lap_numbers],
                }
                for r in top5
            ],
        },
    }
    _results_cache[session_key] = data
    return data


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.context_processor
def inject_user():
    return {"user": session.get("user")}


@app.route("/")
def home():
    return render_template("home.html", year_options=[{"value": y, "label": y} for y in YEARS])


@app.route("/results/<int:meeting_key>")
def results(meeting_key):
    try:
        meetings = openf1("/meetings", meeting_key=meeting_key)
        race = get_race_session(meeting_key)
    except OpenF1Error:
        return redirect(url_for("home"))
    if not meetings or not race:
        return redirect(url_for("home"))
    return render_template("results.html", meeting=meetings[0], race=race)


# ── JSON API used by the page scripts ─────────────────────────────────────────

def api(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return jsonify(fn(*args, **kwargs))
        except OpenF1Error as e:
            return jsonify(error=str(e)), 502
    return wrapper


@app.route("/api/meetings")
@api
def api_meetings():
    year = request.args.get("year", "")
    if year not in YEARS:
        abort(make_response(jsonify(error="Unknown year."), 400))
    return [{"meeting_key": m["meeting_key"], "meeting_name": m["meeting_name"]} for m in get_meetings(year)]


@app.route("/api/race-session/<int:meeting_key>")
def api_race_session(meeting_key):
    try:
        race = get_race_session(meeting_key)
    except OpenF1Error as e:
        return jsonify(error=str(e)), 502
    if not race:
        return jsonify(error="No Race session found for this Grand Prix."), 404
    return jsonify(session_key=race["session_key"])


@app.route("/api/results/<int:session_key>")
@api
def api_results(session_key):
    return get_results(session_key)


# ── Auth (demo only: any well-formed email/password/code is accepted) ─────────

def display_name(email):
    return re.sub(r"\b\w", lambda m: m.group().upper(), email.split("@")[0].replace(".", " ").replace("_", " "))


def log_in(email):
    session.pop("pending_email", None)
    session["user"] = {"name": display_name(email), "email": email}
    return redirect(url_for("home"))


@app.route("/login", methods=["GET", "POST"])
def login():
    errors, email = {}, request.form.get("email", "").strip()
    if request.method == "POST":
        password = request.form.get("password", "")
        if "@" not in email:
            errors["email"] = "Enter a valid email address."
        if len(password) < 6:
            errors["password"] = "Password must be at least 6 characters."
        if not errors:
            session["pending_email"] = email
            return redirect(url_for("login_verify"))
    session.pop("pending_email", None)
    return render_template("auth.html", mode="login", step="credentials", email=email, errors=errors)


@app.route("/login/verify", methods=["GET", "POST"])
def login_verify():
    email = session.get("pending_email")
    if not email:
        return redirect(url_for("login"))
    errors = {}
    if request.method == "POST":
        otp = re.sub(r"\D", "", request.form.get("otp", ""))
        if len(otp) < 6:
            errors["otp"] = "Enter the 6-digit code."
        else:
            return log_in(email)
    return render_template("auth.html", mode="login", step="2fa", email=email, errors=errors)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    errors, email = {}, request.form.get("email", "").strip()
    if request.method == "POST":
        password, confirm = request.form.get("password", ""), request.form.get("confirm", "")
        if "@" not in email:
            errors["email"] = "Enter a valid email address."
        if len(password) < 8:
            errors["password"] = "Password must be at least 8 characters."
        if confirm != password:
            errors["confirm"] = "Passwords do not match."
        if not errors:
            return log_in(email)
    return render_template("auth.html", mode="signup", step="credentials", email=email, errors=errors)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ── Predictions ───────────────────────────────────────────────────────────────

DRIVERS = [
    {"name": "Max Verstappen",    "team": "Red Bull Racing", "colour": "#3671C6"},
    {"name": "Liam Lawson",       "team": "Red Bull Racing", "colour": "#3671C6"},
    {"name": "Lewis Hamilton",    "team": "Ferrari",         "colour": "#E8002D"},
    {"name": "Charles Leclerc",   "team": "Ferrari",         "colour": "#E8002D"},
    {"name": "George Russell",    "team": "Mercedes",        "colour": "#27F4D2"},
    {"name": "Kimi Antonelli",    "team": "Mercedes",        "colour": "#27F4D2"},
    {"name": "Lando Norris",      "team": "McLaren",         "colour": "#FF8000"},
    {"name": "Oscar Piastri",     "team": "McLaren",         "colour": "#FF8000"},
    {"name": "Fernando Alonso",   "team": "Aston Martin",    "colour": "#229971"},
    {"name": "Lance Stroll",      "team": "Aston Martin",    "colour": "#229971"},
    {"name": "Carlos Sainz",      "team": "Williams",        "colour": "#64C4FF"},
    {"name": "Alexander Albon",   "team": "Williams",        "colour": "#64C4FF"},
    {"name": "Pierre Gasly",      "team": "Alpine",          "colour": "#FF87BC"},
    {"name": "Jack Doohan",       "team": "Alpine",          "colour": "#FF87BC"},
    {"name": "Yuki Tsunoda",      "team": "Racing Bulls",    "colour": "#6692FF"},
    {"name": "Isack Hadjar",      "team": "Racing Bulls",    "colour": "#6692FF"},
    {"name": "Nico Hülkenberg",   "team": "Kick Sauber",     "colour": "#52E252"},
    {"name": "Gabriel Bortoleto", "team": "Kick Sauber",     "colour": "#52E252"},
    {"name": "Esteban Ocon",      "team": "Haas",            "colour": "#B6BABD"},
    {"name": "Oliver Bearman",    "team": "Haas",            "colour": "#B6BABD"},
]
DRIVERS_BY_NAME = {d["name"]: d for d in DRIVERS}

# Sample history shown to every signed-in user
PAST_PREDICTIONS = [
    {"grand_prix": "Italian Grand Prix", "year": 2026, "status": "partial", "points": 15,
     "picks": ["Lando Norris", "Charles Leclerc", "Oscar Piastri"],
     "actual": ["Charles Leclerc", "Lando Norris", "George Russell"]},
    {"grand_prix": "Belgian Grand Prix", "year": 2026, "status": "partial", "points": 10,
     "picks": ["Max Verstappen", "Lando Norris", "Lewis Hamilton"],
     "actual": ["Max Verstappen", "Oscar Piastri", "Lando Norris"]},
    {"grand_prix": "Hungarian Grand Prix", "year": 2026, "status": "correct", "points": 25,
     "picks": ["Lewis Hamilton", "Charles Leclerc", "Lando Norris"],
     "actual": ["Lewis Hamilton", "Charles Leclerc", "Lando Norris"]},
    {"grand_prix": "Austrian Grand Prix", "year": 2026, "status": "incorrect", "points": 0,
     "picks": ["Max Verstappen", "George Russell", "Fernando Alonso"],
     "actual": ["Lando Norris", "Oscar Piastri", "Lewis Hamilton"]},
    {"grand_prix": "Dutch Grand Prix", "year": 2026, "status": "locked", "points": None,
     "picks": ["Max Verstappen", "Lando Norris", "Charles Leclerc"], "actual": None},
]

# Status badge colours: dot, text, background, border
BADGES = {
    "open":      ("Open",      "#22c55e", "#4ade80", "rgba(34,197,94,0.08)",  "rgba(34,197,94,0.2)"),
    "locked":    ("Locked",    "#f59e0b", "#fbbf24", "rgba(245,158,11,0.08)", "rgba(245,158,11,0.2)"),
    "correct":   ("Correct",   "#22c55e", "#4ade80", "rgba(34,197,94,0.08)",  "rgba(34,197,94,0.2)"),
    "partial":   ("Partial",   "#f97316", "#fb923c", "rgba(249,115,22,0.08)", "rgba(249,115,22,0.2)"),
    "incorrect": ("Incorrect", "#E8002D", "#f87171", "rgba(232,0,45,0.08)",   "rgba(232,0,45,0.2)"),
}
app.jinja_env.globals.update(BADGES=BADGES, DRIVERS_BY_NAME=DRIVERS_BY_NAME)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


@app.route("/predictions", methods=["GET", "POST"])
@login_required
def predictions():
    picks = session.get("pick") or ["", "", ""]
    error = ""
    editing = request.method == "POST" or "edit" in request.args

    if request.method == "POST":
        picks = [request.form.get(f"p{i}", "") for i in (1, 2, 3)]
        if not all(picks):
            error = "Select a driver for each position."
        elif len(set(picks)) < 3:
            error = "Each position must be a different driver."
        elif not all(p in DRIVERS_BY_NAME for p in picks):
            error = "Unknown driver."
        else:
            session["pick"] = picks
            return redirect(url_for("predictions"))

    history = list(PAST_PREDICTIONS)
    if session.get("pick"):
        history.insert(0, {"grand_prix": "Singapore Grand Prix", "year": 2026, "status": "open",
                           "points": None, "picks": session["pick"], "actual": None})

    return render_template(
        "predictions.html",
        drivers=DRIVERS,
        driver_options=[{"value": d["name"], "label": d["name"]} for d in DRIVERS],
        picks=picks,
        submitted=bool(session.get("pick")) and not editing,
        error=error,
        history=history,
        total_points=sum(p["points"] or 0 for p in history),
    )
