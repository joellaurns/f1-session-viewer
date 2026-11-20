"""Password hashing: HMAC-SHA256 with a Vault-held pepper, then Argon2id.

The pepper lives in Vault (KV v2, mount ``secret``, path ``f1/pepper``) and is
fetched with AppRole credentials from the environment when this module is
imported. Everything about that is fail-closed: missing environment variables,
a failed login, an unreadable secret, a malformed or empty pepper — any of
those raises and the import fails. There is no fallback pepper and no
unpeppered mode.

The secret id is removed from ``os.environ`` as soon as the login attempt is
over, so it isn't inherited by anything else in the process.

Nothing here logs anything, and no password, hash or pepper is ever put into
an exception message or a log line.
"""

import base64
import hashlib
import hmac
import os

import hvac
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Where the pepper lives in Vault.
VAULT_KV_MOUNT = "secret"
PEPPER_PATH = "f1/pepper"

# Argon2id parameters. Changing these makes needs_rehash() report True for
# hashes made with the old settings.
HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


class PepperError(RuntimeError):
    """Raised when the pepper cannot be loaded. Never carries secret values."""


def _require_env(name):
    value = os.environ.get(name)
    if not value:
        raise PepperError(f"{name} is not set")
    return value


def _load_pepper():
    """Log in to Vault with AppRole and return the pepper as bytes."""
    addr = _require_env("VAULT_ADDR")
    cacert = _require_env("VAULT_CACERT")
    role_id = _require_env("VAULT_ROLE_ID")
    secret_id = _require_env("VAULT_SECRET_ID")

    client = hvac.Client(url=addr, verify=cacert)
    try:
        client.auth.approle.login(
            role_id=role_id, secret_id=secret_id, use_token=True
        )
    except Exception as exc:
        raise PepperError("Vault AppRole login failed") from exc
    finally:
        # The secret id is single-use and must not linger in the environment.
        os.environ.pop("VAULT_SECRET_ID", None)

    if not client.is_authenticated():
        raise PepperError("Vault AppRole login did not authenticate the client")

    try:
        response = client.secrets.kv.v2.read_secret_version(
            path=PEPPER_PATH, mount_point=VAULT_KV_MOUNT
        )
        data = response["data"]["data"]
    except Exception as exc:
        raise PepperError(
            f"could not read {VAULT_KV_MOUNT}/{PEPPER_PATH} from Vault"
        ) from exc

    pepper = data.get("pepper")
    if pepper is None and len(data) == 1:
        # Also accept a secret that stores the pepper under a single other key.
        pepper = next(iter(data.values()))

    if not pepper:
        raise PepperError(f"{VAULT_KV_MOUNT}/{PEPPER_PATH} holds an empty pepper")
    if isinstance(pepper, str):
        return pepper.encode("utf-8")
    if isinstance(pepper, bytes):
        return pepper
    raise PepperError(f"{VAULT_KV_MOUNT}/{PEPPER_PATH} pepper is not a string")


PEPPER = _load_pepper()


def _peppered(password):
    """HMAC-SHA256 the password with the pepper, ready for Argon2."""
    digest = hmac.new(PEPPER, password.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest)


def hash_password(password):
    """Return a salted Argon2id hash of the peppered password."""
    return HASHER.hash(_peppered(password))


def verify_password(stored_hash, password):
    """Return True when the password matches the stored hash, False otherwise."""
    if not stored_hash or not password:
        return False
    try:
        return HASHER.verify(stored_hash, _peppered(password))
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(stored_hash):
    """Return True when the stored hash was made with different parameters."""
    return HASHER.check_needs_rehash(stored_hash)
