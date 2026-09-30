"""Generate local-only credentials without printing secrets."""

import secrets
from pathlib import Path

p = Path(".env")
if p.exists():
    print("Existing .env preserved")
else:
    content = Path(".env.example").read_text()
    content = content.replace("CHANGE_ME_32_OR_MORE_CHARACTERS", secrets.token_urlsafe(40))
    content = content.replace("CHANGE_ME", secrets.token_urlsafe(24))
    p.write_text(content)
    p.chmod(0o600)
    print(
        "Created .env (mode 0600). Demo role passwords are local, generated, and shared only through your private .env."
    )
