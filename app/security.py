"""Password hashing (PBKDF2) and signed-cookie sessions."""
import hashlib
import hmac
import os

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

_PBKDF_ROUNDS = 200_000
_serializer = URLSafeTimedSerializer(settings.session_secret, salt="blinksbright-session")
_chat_serializer = URLSafeTimedSerializer(settings.session_secret, salt="blinksbright-chat")
_calendar_serializer = URLSafeTimedSerializer(settings.session_secret, salt="blinksbright-calendar")
# Customers get their OWN salt and cookie. A staff session and a customer session
# must never be interchangeable: same secret, different salt means a token minted
# for one is rejected by the other's loads() rather than silently granting access.
_customer_serializer = URLSafeTimedSerializer(settings.session_secret, salt="blinksbright-customer")
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 days
CHAT_MAX_AGE = 60 * 60 * 24 * 7      # 7 days
SESSION_COOKIE = "session"


def make_chat_token(conversation_id: int) -> str:
    """Signed token that lets a web-chat widget stream one conversation."""
    return _chat_serializer.dumps({"cid": conversation_id})


def read_chat_token(token: str | None) -> int | None:
    if not token:
        return None
    try:
        return _chat_serializer.loads(token, max_age=CHAT_MAX_AGE).get("cid")
    except Exception:
        return None


def make_calendar_token(clinic_id: int, branch_id: int | None = None) -> str:
    """Signed token for a clinic's ICS calendar-subscription feed."""
    data = {"clid": clinic_id}
    if branch_id:
        data["bid"] = branch_id
    return _calendar_serializer.dumps(data)


def read_calendar_token(token: str | None) -> dict | None:
    """Return the calendar-token payload, or None if invalid. Read with NO
    max_age — calendar apps poll a subscribe URL for years."""
    if not token:
        return None
    try:
        return _calendar_serializer.loads(token)
    except Exception:
        return None


def hash_password(password: str) -> str:
    """Return a ``salt$hash`` string for a plaintext password."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF_ROUNDS)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a plaintext password against a stored ``salt$hash``."""
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), _PBKDF_ROUNDS
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def make_session(user_id: int, clinic_id: int | None = None) -> str:
    """Create a signed session token carrying the user and the active clinic."""
    return _serializer.dumps({"uid": user_id, "cid": clinic_id})


def read_session(token: str | None) -> dict | None:
    """Return ``{'uid', 'cid'}`` from a session token, or None if invalid/expired."""
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return {"uid": data.get("uid"), "cid": data.get("cid")}
    except (BadSignature, SignatureExpired, Exception):
        return None


CUSTOMER_COOKIE = "cust_session"


def make_customer_session(customer_id: int) -> str:
    """Sign a customer-portal session (app/routers/portal.py)."""
    return _customer_serializer.dumps({"cust": customer_id})


def read_customer_session(token: str | None) -> int | None:
    """Customer id from a portal session cookie, or None if absent/invalid/expired."""
    if not token:
        return None
    try:
        data = _customer_serializer.loads(token, max_age=SESSION_MAX_AGE)
    except Exception:
        return None
    cid = data.get("cust") if isinstance(data, dict) else None
    return cid if isinstance(cid, int) else None
