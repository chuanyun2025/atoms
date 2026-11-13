"""Backfill a separate internal service token in existing, ignored env files."""
import secrets


def ensure_gateway_token(path):
    with path.open("r+", encoding="utf-8", newline="") as config:
        text = config.read()
        lines = text.splitlines(keepends=True)
        if any(line.startswith("PROVIDER_GATEWAY_TOKEN=") and line.partition("=")[2].strip() for line in lines):
            return
        text = "".join(line for line in lines if not line.startswith("PROVIDER_GATEWAY_TOKEN="))
        config.seek(0)
        config.write(text.rstrip("\r\n")+"\nPROVIDER_GATEWAY_TOKEN="+secrets.token_urlsafe(32)+"\n")
        config.truncate()
