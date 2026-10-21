"""Password hashing and database-backed limits shared by API processes."""

import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy.dialects.postgresql import insert

from resolveflow.domain.common import DomainError, canonical
from resolveflow.storage.models import RateBucket, now


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f"scrypt:{salt.hex()}:{digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        kind, salt, expected = encoded.split(":")
        if kind != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def consume_limit(factory, namespace: str, subject: str, limit: int, seconds: int = 60):
    current = now()
    window = int(current.timestamp()) // seconds
    key = canonical({"namespace": namespace, "subject": subject, "window": window})
    # A separate transaction records rejected attempts as well as successful ones.
    with factory.begin() as s:
        count = s.scalar(
            insert(RateBucket)
            .values(key=key, hits=1, expires_at=current + timedelta(seconds=seconds * 2))
            .on_conflict_do_update(
                index_elements=[RateBucket.key], set_={"hits": RateBucket.hits + 1}
            )
            .returning(RateBucket.hits)
        )
    if count > limit:
        raise DomainError("rate_limited", "Request budget reached. Please try again shortly.", 429)
