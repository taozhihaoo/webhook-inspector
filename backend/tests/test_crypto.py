"""Secret handling: encryption at rest, token hashing, constant-time compare."""

import pytest
from app.services.crypto import (
    decrypt_secret,
    encrypt_secret,
    hash_token,
    secrets_equal,
)


class TestEncryption:
    def test_round_trip(self):
        ciphertext = encrypt_secret("whsec_abc123", "key-a")
        assert ciphertext != "whsec_abc123"
        assert "whsec" not in ciphertext
        assert decrypt_secret(ciphertext, "key-a") == "whsec_abc123"

    def test_wrong_key_fails(self):
        ciphertext = encrypt_secret("secret", "key-a")
        with pytest.raises(RuntimeError):
            decrypt_secret(ciphertext, "key-b")

    def test_ciphertext_is_deterministic_per_key_but_differs_per_value(self):
        a1 = encrypt_secret("value-a", "key")
        a2 = encrypt_secret("value-a", "key")
        assert a1 != a2  # Fernet includes a timestamp+IV
        assert decrypt_secret(a1, "key") == decrypt_secret(a2, "key")


class TestTokenHashing:
    def test_hash_is_sha256_hex(self):
        import hashlib

        assert hash_token("tok") == hashlib.sha256(b"tok").hexdigest()

    def test_hash_hides_original(self):
        assert "my-plain-token" not in hash_token("my-plain-token")


class TestConstantTimeCompare:
    def test_equal(self):
        assert secrets_equal("abc", "abc")

    def test_not_equal(self):
        assert not secrets_equal("abc", "abd")
        assert not secrets_equal("abc", "abcd")
        assert not secrets_equal("", "x")
