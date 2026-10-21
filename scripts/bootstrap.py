"""Complete local configuration while preserving existing private settings."""

import secrets
from pathlib import Path

from dotenv import dotenv_values

path = Path(".env")
existing = dict(dotenv_values(path)) if path.exists() else {}
values = dict(dotenv_values(".env.example"))
for key in (
    "POSTGRES_PASSWORD",
    "SESSION_SECRET",
    "OPERATOR_PASSWORD",
    "SUPERVISOR_PASSWORD",
    "DEVELOPER_PASSWORD",
):
    value = existing.get(key)
    values[key] = value if value and "CHANGE_ME" not in value else secrets.token_urlsafe(40)
values["DATABASE_URL"] = (
    f"postgresql+psycopg://resolveflow:{values['POSTGRES_PASSWORD']}@localhost:55432/resolveflow"
)
for key, value in existing.items():
    if value is not None and "CHANGE_ME" not in value:
        values[key] = value
lines = []
for line in Path(".env.example").read_text().splitlines():
    key = line.split("=", 1)[0]
    lines.append(f"{key}={values.pop(key)}" if key in values else line)
lines.extend(f"{key}={value}" for key, value in values.items())
path.write_text("\n".join(lines) + "\n")
path.chmod(0o600)
print("Local configuration is complete (mode 0600); existing credentials were preserved.")
