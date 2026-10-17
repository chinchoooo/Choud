"""Time-based one-time passwords (RFC 6238) with the standard library only.

This is the same 30-second, 6-digit, HMAC-SHA1 scheme every authenticator app (Google
Authenticator, Aegis, 1Password, Authy...) understands. HMAC and base32 come from the standard
library; only the small, fully specified truncation step is written here, and the tests check it
against the RFC's published vectors.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

PERIOD = 30
DIGITS = 6
# Accept the previous and next 30-second window, for clocks that are a little off.
WINDOW = 1


def new_secret() -> str:
    """160 random bits, base32 (the form authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def code_at(secret: str, step: int, digits: int = DIGITS) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**digits).zfill(digits)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def verify(
    secret: str, code: str, last_step: int | None = None, now: float | None = None
) -> int | None:
    """The 30-second step this code belongs to, or None if it is wrong or already used.

    A step at or before `last_step` is refused, so a code that was just used (or one an attacker
    saw over a shoulder) cannot be replayed.
    """
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    step_now = current_step(now)
    matched = None
    for step in range(step_now - WINDOW, step_now + WINDOW + 1):
        # Compare every candidate so timing does not reveal which one was close.
        if hmac.compare_digest(code_at(secret, step), code) and matched is None:
            matched = step
    if matched is None or (last_step is not None and matched <= last_step):
        return None
    return matched


def otpauth_uri(secret: str, account: str, issuer: str = "Choud") -> str:
    label = quote(f"{issuer}:{account}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"
    )
