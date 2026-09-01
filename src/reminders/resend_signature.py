"""Svix signature check for the Resend webhook (delivery proof).

Resend signs webhooks with the Svix scheme: the secret is `whsec_<base64>`,
the signed content is `{svix-id}.{svix-timestamp}.{raw body}`, and the
`svix-signature` header carries space-separated `v1,<base64 hmac>` entries
(several during a secret rotation — ONE match suffices). Same doctrine as
paddle_signature: raw bytes, constant-time compare, replay tolerance."""

import base64
import hashlib
import hmac
import time

REPLAY_TOLERANCE_SECONDS = 300


def verify_resend_signature(
    raw_body: bytes,
    svix_id: str | None,
    svix_timestamp: str | None,
    svix_signature: str | None,
    secret: str,
) -> bool:
    if not svix_id or not svix_timestamp or not svix_signature:
        return False
    if not svix_timestamp.isdigit():
        return False
    if abs(time.time() - int(svix_timestamp)) > REPLAY_TOLERANCE_SECONDS:
        return False
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"))
    except Exception:  # noqa: BLE001 — a malformed secret can only deny
        return False
    signed = f"{svix_id}.{svix_timestamp}.".encode() + raw_body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for entry in svix_signature.split(" "):
        _version, _, candidate = entry.partition(",")
        if candidate and hmac.compare_digest(expected, candidate):
            return True
    return False
