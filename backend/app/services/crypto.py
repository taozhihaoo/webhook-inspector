"""Secret handling: encryption of signature secrets at rest, token hashing.

Signature secrets must be recoverable (HMAC needs them), so they are stored
encrypted with a key derived from SECRET_KEY. Ingest tokens are only needed
for comparison, so they are stored as SHA-256 hashes.
"""

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken


def _fernet(secret_key: str) -> Fernet:
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str, secret_key: str) -> str:
    return _fernet(secret_key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str, secret_key: str) -> str:
    try:
        return _fernet(secret_key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:  # wrong SECRET_KEY or corrupted value
        raise RuntimeError("Failed to decrypt stored secret; check SECRET_KEY") from exc


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def secrets_equal(provided: str, stored: str) -> bool:
    """Constant-time equality for token/hash comparisons."""
    return hmac.compare_digest(provided.encode("utf-8"), stored.encode("utf-8"))
