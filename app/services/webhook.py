import hashlib
import hmac


def verify_bling_signature(raw_body: bytes, signature_header: str | None, client_secret: str) -> bool:
    if not signature_header or not client_secret:
        return False

    expected_prefix = "sha256="
    if not signature_header.startswith(expected_prefix):
        return False

    received = signature_header[len(expected_prefix) :]
    computed = hmac.new(
        client_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(received, computed)
