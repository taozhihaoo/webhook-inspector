"""Generic HMAC signature verification for inbound webhooks.

The signature is always computed over the raw request body (never a
re-serialized JSON document) and compared in constant time.
"""

import base64
import hashlib
import hmac

SUPPORTED_ALGORITHMS = {
    "hmac-sha256": hashlib.sha256,
    "hmac-sha1": hashlib.sha1,
    "hmac-sha384": hashlib.sha384,
    "hmac-sha512": hashlib.sha512,
}

# Providers commonly prefix the digest, e.g. GitHub's "sha256=abcdef...". We
# accept an "<algorithm-short-name>=" prefix on the header value.
_PREFIXES = {name: name.split("-")[1] + "=" for name in SUPPORTED_ALGORITHMS}


def compute_signature(secret: str | bytes, body: bytes, algorithm: str, encoding: str) -> str:
    try:
        hasher = SUPPORTED_ALGORITHMS[algorithm]
    except KeyError as exc:
        raise ValueError(f"Unsupported signature algorithm: {algorithm}") from exc

    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
    digest = hmac.new(secret_bytes, body, hasher).digest()
    if encoding == "hex":
        return digest.hex()
    if encoding == "base64":
        return base64.b64encode(digest).decode("ascii")
    raise ValueError(f"Unsupported signature encoding: {encoding}")


def verify_signature(
    secret: str | bytes, body: bytes, provided: str, algorithm: str, encoding: str
) -> bool:
    expected = compute_signature(secret, body, algorithm, encoding)
    candidate = provided.strip()
    prefix = _PREFIXES.get(algorithm)
    if prefix and candidate.lower().startswith(prefix):
        candidate = candidate[len(prefix) :]
    return hmac.compare_digest(candidate, expected)
