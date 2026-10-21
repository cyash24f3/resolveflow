import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def canonical(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone offset")
    return parsed.astimezone(UTC)


def clock(run) -> datetime:
    return instant(run.clock) if run.clock else datetime.now(UTC)


@dataclass(frozen=True)
class Scope:
    actor: str
    role: str
    workspace: str
    customers: tuple[str, ...]

    def require(self, role: str):
        if self.role != role:
            raise DomainError("forbidden", "This role cannot perform that action", 403)

    def customer(self, customer_id: str):
        if customer_id not in self.customers:
            raise DomainError("not_found", "Record not found", 404)
