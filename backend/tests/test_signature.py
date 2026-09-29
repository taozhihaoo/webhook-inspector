"""Generic HMAC signature verification (unit + integration)."""

import base64
import hashlib
import hmac

from app.services.signature import compute_signature, verify_signature


class TestSignatureUnit:
    body = b'{"event": "order.created"}'
    secret = "whsec_test_123"

    def test_hmac_sha256_hex_known_vector(self):
        expected = hmac.new(self.secret.encode(), self.body, hashlib.sha256).hexdigest()
        assert compute_signature(self.secret, self.body, "hmac-sha256", "hex") == expected

    def test_hmac_sha256_base64(self):
        digest = hmac.new(self.secret.encode(), self.body, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode()
        assert compute_signature(self.secret, self.body, "hmac-sha256", "base64") == expected

    def test_all_algorithms(self):
        for algorithm in ("hmac-sha1", "hmac-sha256", "hmac-sha384", "hmac-sha512"):
            sig = compute_signature(self.secret, self.body, algorithm, "hex")
            assert len(sig) > 20
            assert verify_signature(self.secret, self.body, sig, algorithm, "hex")

    def test_verify_positive(self):
        sig = compute_signature(self.secret, self.body, "hmac-sha256", "hex")
        assert verify_signature(self.secret, self.body, sig, "hmac-sha256", "hex")

    def test_verify_wrong_secret(self):
        sig = compute_signature(self.secret, self.body, "hmac-sha256", "hex")
        assert not verify_signature("other", self.body, sig, "hmac-sha256", "hex")

    def test_verify_tampered_body(self):
        sig = compute_signature(self.secret, self.body, "hmac-sha256", "hex")
        assert not verify_signature(
            self.secret, self.body + b" tampered", sig, "hmac-sha256", "hex"
        )

    def test_provider_prefix_tolerated(self):
        sig = compute_signature(self.secret, self.body, "hmac-sha256", "hex")
        assert verify_signature(self.secret, self.body, f"sha256={sig}", "hmac-sha256", "hex")

    def test_signature_is_over_raw_body(self):
        # Same bytes in, same signature out regardless of any JSON formatting.
        raw = b'{"a": 1,  "b":2}'
        reserialized = b'{"a": 1, "b": 2}'
        assert compute_signature(self.secret, raw, "hmac-sha256", "hex") != compute_signature(
            self.secret, reserialized, "hmac-sha256", "hex"
        )

    def test_unsupported_algorithm_raises(self):
        import pytest

        with pytest.raises(ValueError):
            compute_signature(self.secret, self.body, "hmac-md5", "hex")


class TestSignatureIntegration:
    def _sig(self, secret: str, body: bytes, encoding: str = "hex") -> str:
        return compute_signature(secret, body, "hmac-sha256", encoding)

    async def test_verified(self, client, make_endpoint):
        ep = await make_endpoint(
            signature={
                "enabled": True,
                "header": "X-Signature",
                "algorithm": "hmac-sha256",
                "encoding": "hex",
                "secret": "whsec_abc",
            }
        )
        body = b'{"order_id": 1}'
        resp = await client.post(
            ep["webhook_url"],
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": self._sig("whsec_abc", body),
            },
        )
        assert resp.status_code == 200
        detail = await _latest(client, ep["id"])
        assert detail["signature_status"] == "verified"

    async def test_invalid_signature_recorded_but_still_captured(self, client, make_endpoint):
        ep = await make_endpoint(
            signature={
                "enabled": True,
                "header": "X-Signature",
                "algorithm": "hmac-sha256",
                "encoding": "hex",
                "secret": "whsec_abc",
            }
        )
        body = b'{"order_id": 1}'
        resp = await client.post(
            ep["webhook_url"],
            content=body,
            headers={"Content-Type": "application/json", "X-Signature": "deadbeef"},
        )
        assert resp.status_code == 200  # capture-first: bad signature is flagged, not dropped
        detail = await _latest(client, ep["id"])
        assert detail["signature_status"] == "invalid"
        assert detail["body_text"] == body.decode()

    async def test_missing_header_when_configured(self, client, make_endpoint):
        ep = await make_endpoint(
            signature={
                "enabled": True,
                "header": "X-Signature",
                "algorithm": "hmac-sha256",
                "encoding": "hex",
                "secret": "whsec_abc",
            }
        )
        await client.post(ep["webhook_url"], json={"a": 1})
        detail = await _latest(client, ep["id"])
        assert detail["signature_status"] == "invalid"

    async def test_base64_encoding(self, client, make_endpoint):
        ep = await make_endpoint(
            signature={
                "enabled": True,
                "header": "X-Hub-Signature",
                "algorithm": "hmac-sha256",
                "encoding": "base64",
                "secret": "whsec_b64",
            }
        )
        body = b"payload-bytes"
        resp = await client.post(
            ep["webhook_url"],
            content=body,
            headers={"X-Hub-Signature": self._sig("whsec_b64", body, "base64")},
        )
        assert resp.status_code == 200
        detail = await _latest(client, ep["id"])
        assert detail["signature_status"] == "verified"

    async def test_prefixed_header_value(self, client, make_endpoint):
        ep = await make_endpoint(
            signature={
                "enabled": True,
                "header": "X-Signature",
                "algorithm": "hmac-sha256",
                "encoding": "hex",
                "secret": "whsec_abc",
            }
        )
        body = b"x"
        resp = await client.post(
            ep["webhook_url"],
            content=body,
            headers={"X-Signature": "sha256=" + self._sig("whsec_abc", body)},
        )
        assert resp.status_code == 200
        assert (await _latest(client, ep["id"]))["signature_status"] == "verified"

    async def test_secret_never_exposed(self, client, app, make_endpoint):
        ep = await make_endpoint(
            signature={
                "enabled": True,
                "header": "X-Signature",
                "algorithm": "hmac-sha256",
                "encoding": "hex",
                "secret": "super-secret-value",
            }
        )
        text = (await client.get(f"/api/endpoints/{ep['id']}")).text
        assert "super-secret-value" not in text
        # And not stored in plaintext in the database.
        from app.models import WebhookEndpoint
        from sqlalchemy import select

        async with app.state.session_factory() as session:
            stored = await session.scalar(
                select(WebhookEndpoint.signature_secret_encrypted).where(
                    WebhookEndpoint.id == ep["id"]
                )
            )
        assert stored is not None
        assert "super-secret-value" not in stored


async def _latest(client, endpoint_id: int) -> dict:
    lst = await client.get(f"/api/endpoints/{endpoint_id}/requests")
    item = lst.json()["data"]["items"][0]
    return (await client.get(f"/api/requests/{item['id']}")).json()["data"]
