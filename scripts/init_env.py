"""Create ignored local configuration without printing secrets."""
from pathlib import Path
import secrets
from provider_gateway_token import ensure_gateway_token

root = Path(__file__).resolve().parents[1]
target = root / ".env.local"
if not target.exists():
    text = (root / ".env.example").read_text(encoding="utf-8")
    text = text.replace("SESSION_SECRET=\n", "SESSION_SECRET=" + secrets.token_urlsafe(48) + "\n")
    text = text.replace("SERVICE_TOKEN=\n", "SERVICE_TOKEN=" + secrets.token_urlsafe(32) + "\n")
    target.write_text(text, encoding="utf-8")
    print("Created .env.local (secrets hidden).")
else:
    print(".env.local already exists; preserved.")
ensure_gateway_token(target)
