"""Production configuration security: weak secrets refuse to boot, no leaks."""

import hashlib
import logging

import pytest
from app.config import Settings
from app.services.signature import compute_signature
from pydantic import ValidationError

STRONG = "s" * 32


class TestProductionSecretPolicy:
    def test_missing_required_secrets_rejected(self, monkeypatch):
        # Isolate from conftest env vars and any local .env file.
        monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings(app_env="development", _env_file=None)

    def test_weak_default_token_rejected_in_production(self):
        with pytest.raises(ValidationError) as excinfo:
            Settings(
                app_env="production",
                admin_api_token="change-me-admin-token",
                secret_key=STRONG,
            )
        assert "ADMIN_API_TOKEN" in str(excinfo.value)

    def test_weak_default_secret_key_rejected_in_production(self):
        with pytest.raises(ValidationError) as excinfo:
            Settings(
                app_env="production",
                admin_api_token=STRONG,
                secret_key="dev-secret-key-change-me-0123456789abcdef",
            )
        assert "SECRET_KEY" in str(excinfo.value)

    def test_short_secrets_rejected_in_production(self):
        with pytest.raises(ValidationError):
            Settings(app_env="production", admin_api_token="short", secret_key=STRONG)
        with pytest.raises(ValidationError):
            Settings(app_env="production", admin_api_token=STRONG, secret_key="a" * 10)

    def test_identical_token_and_key_rejected_in_production(self):
        same = "B" * 32
        # Reusing one value for both is a real-world misconfiguration.
        with pytest.raises(ValidationError):
            Settings(app_env="production", admin_api_token=same, secret_key=same)

    def test_weak_values_fine_outside_production(self):
        settings = Settings(
            app_env="development",
            admin_api_token="dev-admin-token-change-me",
            secret_key="dev-secret-key-change-me-0123456789abcdef",
        )
        assert settings.app_env == "development"


class TestSecretLeakage:
    async def test_health_response_is_secret_free(self, client, app):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body["data"].keys()) == {"status", "version", "database"}
        token = app.state.settings.admin_api_token
        secret_key = app.state.settings.secret_key
        assert token not in resp.text and secret_key not in resp.text

    async def test_secrets_never_appear_in_logs(self, client, app, make_endpoint, caplog):
        ingest_token = "tok_log-leak-probe-123"
        signature_secret = "whsec_log-leak-probe-456"
        ep = await make_endpoint(
            ingest_token=ingest_token,
            signature={
                "enabled": True,
                "header": "X-Signature",
                "algorithm": "hmac-sha256",
                "encoding": "hex",
                "secret": signature_secret,
            },
        )
        body = b'{"probe": true}'
        signature = compute_signature(signature_secret, body, "hmac-sha256", "hex")

        with caplog.at_level(logging.DEBUG):
            resp = await client.post(
                ep["webhook_url"],
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Token": ingest_token,
                    "X-Signature": signature,
                    "Authorization": "Bearer test-admin-token",
                },
            )
            assert resp.status_code == 200
            await client.get("/api/endpoints")
            await client.get(f"/api/requests/{ep['id']}")

        for leak in (
            ingest_token,
            signature_secret,
            "test-admin-token",
            "test-secret-key-for-unit-tests",
            body.decode(),
        ):
            assert leak not in caplog.text, leak

    async def test_signature_secret_not_in_any_endpoint_payload(self, client, make_endpoint):
        secret = "whsec_endpoints-scan-789"
        ep = await make_endpoint(
            signature={
                "enabled": True,
                "header": "X-Signature",
                "algorithm": "hmac-sha256",
                "encoding": "hex",
                "secret": secret,
            }
        )
        listing = await client.get("/api/endpoints")
        detail = await client.get(f"/api/endpoints/{ep['id']}")
        assert secret not in listing.text
        assert secret not in detail.text

    def test_secret_hashing_is_not_reversible(self):
        from app.services.crypto import hash_token

        digest = hash_token("some-ingest-token")
        assert "some-ingest-token" not in digest
        assert digest == hashlib.sha256(b"some-ingest-token").hexdigest()
