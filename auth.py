"""Authentication internals: password policy, in-memory accounts, and TOTP.

For now accounts live only in server memory and passwords are compared as-is.
That is deliberate scaffolding: persistence and password hashing are the next
step and the call sites in app.py are already shaped for it.

The second factor is a standard TOTP secret, which Microsoft Authenticator
(and any other authenticator app) enrols by scanning the otpauth:// URI we
render at sign-up.
"""

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from urllib.parse import quote, urlencode

# Password policy — NIST SP 800-63B: 8 characters is acceptable when MFA is
# enabled, 15 when it is not. The maximum must be at least 64; we allow 128.
PASSWORD_MIN_WITH_MFA = 8
PASSWORD_MIN_WITHOUT_MFA = 15
PASSWORD_MAX = 128

# TOTP parameters. Microsoft Authenticator expects SHA-1/6 digits/30 seconds.
TOTP_ISSUER = "F1 Session Viewer"
TOTP_STEP = 30
TOTP_DIGITS = 6
TOTP_WINDOW = 1  # accept one step of clock drift either way

PENDING_TTL = 10 * 60  # seconds to finish enrolling an authenticator
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 5 * 60

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailTaken(Exception):
    """Raised when an account for that address already exists."""


def normalize_email(value):
    return (value or "").strip().lower()


def valid_email(value):
    return len(value) <= 254 and bool(EMAIL_RE.match(value))


# ── Accounts (in memory only — persistence comes later) ──────────────────────
# TODO: replace with a real user store and password hashing once we get there.

_users_by_email = {}
_next_user_id = 1


def get_user(user_id):
    if not user_id:
        return None
    for user in _users_by_email.values():
        if user["id"] == user_id:
            return user
    return None


def get_user_by_email(email):
    return _users_by_email.get(email)


def create_user(email, password, totp_secret):
    global _next_user_id
    if email in _users_by_email:
        raise EmailTaken(email)
    user = {
        "id": _next_user_id,
        "email": email,
        "password": password,
        "totp_secret": totp_secret,
        "mfa_enabled": True,
        "failed_attempts": 0,
        "locked_until": None,
        "last_totp_counter": 0,
    }
    _next_user_id += 1
    _users_by_email[email] = user
    return user


# ── Password policy ───────────────────────────────────────────────────────────

# Common passwords we refuse outright. Matching is exact and case-insensitive.
# (A production deployment would swap this for a breached-password service.)
COMMON_PASSWORDS = {
    "password", "password1", "password12", "password123", "password1234",
    "password!", "password1!", "p@ssw0rd", "p@ssword1", "passw0rd",
    "12345678", "123456789", "1234567890", "qwerty123", "qwerty123!",
    "qwertyuiop", "abc12345", "letmein1", "welcome1", "welcome123",
    "admin123", "administrator", "iloveyou1", "monkey123", "dragon123",
    "football1", "baseball1", "sunshine1", "princess1", "superman1",
    "trustno1", "master123", "shadow123", "michael1", "jennifer1",
    "computer1", "whatever1",
}


def password_policy_errors(password, mfa_enabled, email=""):
    """Return every policy violation (empty list when the password is fine).

    Length follows NIST SP 800-63B (8 with MFA, 15 without, max at least 64),
    plus the usual uppercase/lowercase/number rules. There is no symbol
    requirement and no list of disallowed characters.
    """
    errors = []
    minimum = PASSWORD_MIN_WITH_MFA if mfa_enabled else PASSWORD_MIN_WITHOUT_MFA

    if len(password) < minimum:
        if mfa_enabled:
            errors.append(f"Password must be at least {minimum} characters.")
        else:
            errors.append(
                f"Password must be at least {minimum} characters when two-factor authentication is not enabled."
            )
    if len(password) > PASSWORD_MAX:
        errors.append(f"Password must be {PASSWORD_MAX} characters or fewer.")
    if not password.strip():
        errors.append("Password can't be only spaces.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must include an uppercase letter.")
    if not re.search(r"[a-z]", password):
        errors.append("Password must include a lowercase letter.")
    if not re.search(r"\d", password):
        errors.append("Password must include a number.")

    local = email.split("@")[0].strip().lower() if email else ""
    if len(local) >= 3 and local in password.lower():
        errors.append("Password can't contain your email address.")
    if password.lower() in COMMON_PASSWORDS:
        errors.append("That password is too common. Choose something less predictable.")
    return errors



def verify_password(user, password):
    if not password or len(password) > PASSWORD_MAX:
        return False
    return hmac.compare_digest(user["password"], password)


def burn_password_check(password):
    """Spend a little time for unknown accounts (timing defence)."""
    hmac.compare_digest((password or "")[:PASSWORD_MAX], secrets.token_urlsafe(16))


# ── TOTP ──────────────────────────────────────────────────────────────────────

def generate_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def format_secret(secret):
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


def provisioning_uri(email, secret):
    label = quote(f"{TOTP_ISSUER}:{email}", safe="")
    params = urlencode(
        {
            "secret": secret,
            "issuer": TOTP_ISSUER,
            "algorithm": "SHA1",
            "digits": TOTP_DIGITS,
            "period": TOTP_STEP,
        }
    )
    return f"otpauth://totp/{label}?{params}"


def qr_data_uri(uri):
    """Inline SVG QR code; no extra network requests needed to enrol."""
    import segno

    return segno.make(uri, error="m").svg_data_uri(
        scale=4, dark="#0B0E14", light="#FFFFFF"
    )


def _totp_code(secret, counter):
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10 ** TOTP_DIGITS:0{TOTP_DIGITS}d}"


def verify_totp(secret, code, at_time=None):
    """Return the matched time-step counter, or None if the code is invalid.

    A counter is returned so callers can reject replay of a used code.
    """
    code = (code or "").strip()
    if len(code) != TOTP_DIGITS or not code.isdigit():
        return None
    current = int((at_time if at_time is not None else time.time()) // TOTP_STEP)
    for delta in range(-TOTP_WINDOW, TOTP_WINDOW + 1):
        counter = current + delta
        if hmac.compare_digest(_totp_code(secret, counter), code):
            return counter
    return None


def mark_totp_counter(user, counter):
    user["last_totp_counter"] = max(user["last_totp_counter"], counter)


# ── Failed-attempt throttling ────────────────────────────────────────────────

def lockout_remaining(user):
    locked_until = user["locked_until"] or 0
    remaining = locked_until - time.time()
    return max(0, int(remaining + 0.999)) if remaining > 0 else 0


def record_failure(user):
    user["failed_attempts"] += 1
    if user["failed_attempts"] >= MAX_FAILED_ATTEMPTS:
        user["failed_attempts"] = 0
        user["locked_until"] = time.time() + LOCKOUT_SECONDS


def clear_failures(user):
    user["failed_attempts"] = 0
    user["locked_until"] = None


# ── Sign-up in progress ──────────────────────────────────────────────────────
# Kept server-side, keyed by a random token in the signed session cookie, so
# the password never travels back to the browser. Sign-ups that never finish
# expire after PENDING_TTL.

_pending = {}


def _prune_pending():
    now = time.time()
    for token, entry in list(_pending.items()):
        if entry["expires"] <= now:
            _pending.pop(token, None)


def start_pending_signup(email, password):
    _prune_pending()
    token = secrets.token_urlsafe(32)
    _pending[token] = {
        "email": email,
        "password": password,
        "secret": generate_totp_secret(),
        "expires": time.time() + PENDING_TTL,
    }
    return token, _pending[token]


def get_pending_signup(token):
    if not token:
        return None
    _prune_pending()
    return _pending.get(token)


def pop_pending_signup(token):
    _prune_pending()
    return _pending.pop(token, None)
