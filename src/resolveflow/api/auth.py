import hmac
import secrets

from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from resolveflow.domain.common import DomainError, Scope
from resolveflow.settings import get_settings
from resolveflow.storage.db import sessions
from resolveflow.storage.models import Account, AuthSession, now

ROLES = {"operator": ("C-100",), "supervisor": ("C-100", "C-200"), "developer": ("C-100", "C-200")}


def signer():
    secret = get_settings().session_secret.get_secret_value()
    if len(secret) < 32:
        raise DomainError(
            "unavailable", "Session configuration requires a secret of at least 32 characters", 503
        )
    return URLSafeTimedSerializer(secret, salt="resolveflow-session-v1")


def session_payload(role, actor=None, session_id=None):
    return {
        "actor": actor or role,
        "role": role,
        "session_id": session_id,
        "csrf": secrets.token_urlsafe(24),
    }


def identity(request: Request):
    if get_settings().public_read_only and request.method not in ("GET", "HEAD"):
        raise DomainError("forbidden", "Public mode is read only", 403)
    try:
        data = signer().loads(request.cookies.get("rf_session", ""), max_age=28800)
        role = data["role"]
        if role not in ROLES:
            raise BadSignature("invalid role")
    except (BadSignature, SignatureExpired, KeyError) as exc:
        raise DomainError("unauthorized", "Sign in to continue", 401) from exc
    if request.method not in ("GET", "HEAD") and not hmac.compare_digest(
        request.headers.get("x-csrf-token", ""), data["csrf"]
    ):
        raise DomainError("forbidden", "CSRF token required", 403)
    with sessions()() as s:
        active = s.get(AuthSession, data.get("session_id")) if data.get("session_id") else None
        if (
            not active
            or active.revoked
            or active.expires_at <= now()
            or active.actor != data["actor"]
            or active.role != role
        ):
            raise DomainError("unauthorized", "Session expired. Sign in again.", 401)
        if not active.workspace.startswith("guest-"):
            account = s.get(Account, active.actor)
            if account and not account.active:
                raise DomainError("unauthorized", "Account is inactive", 401)
        request.state.session_id = active.id
        return Scope(active.actor, role, active.workspace, tuple(active.customers))
