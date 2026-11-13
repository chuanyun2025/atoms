"""Non-secret identifiers, shared without importing HTTP/session dependencies."""
import secrets

def uid():
    return secrets.token_hex(16)
