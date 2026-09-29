"""Management API for endpoints: CRUD, auth, validation, unguessable IDs."""


from tests.conftest import ADMIN_TOKEN


class TestAdminAuth:
    async def test_missing_token_rejected(self, client):
        client.headers.pop("Authorization")
        resp = await client.get("/api/endpoints")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized"

    async def test_wrong_token_rejected(self, client):
        client.headers["Authorization"] = "Bearer wrong-token"
        resp = await client.get("/api/endpoints")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized"

    async def test_malformed_header_rejected(self, client):
        client.headers["Authorization"] = ADMIN_TOKEN  # missing "Bearer " prefix
        resp = await client.get("/api/endpoints")
        assert resp.status_code == 401

    async def test_token_never_appears_in_responses(self, client, make_endpoint):
        await make_endpoint()
        for path in ("/api/endpoints", "/api/health"):
            resp = await client.get(path)
            assert ADMIN_TOKEN not in resp.text


class TestEndpointCrud:
    async def test_create_returns_full_url(self, client, make_endpoint):
        ep = await make_endpoint(name="stripe sandbox")
        assert ep["name"] == "stripe sandbox"
        assert ep["webhook_url"].startswith("http://testserver/hook/")
        assert ep["status"] == "active"
        assert ep["enabled"] is True
        assert ep["response_status"] == 200
        assert ep["signature"]["configured"] is False
        assert ep["ingest_token_configured"] is False

    async def test_public_ids_unguessable(self, make_endpoint):
        ids = [(await make_endpoint())["public_id"] for _ in range(5)]
        assert len(set(ids)) == 5
        for public_id in ids:
            assert len(public_id) >= 21  # ~128 bits of entropy
            assert public_id.isalnum() or set(public_id) <= set(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            )
            # No sequential/guessable patterns like "1", "test", "abc123".
            assert not public_id.lower().startswith(("test", "abc"))

    async def test_get_detail(self, client, make_endpoint):
        ep = await make_endpoint()
        resp = await client.get(f"/api/endpoints/{ep['id']}")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == ep["id"]

    async def test_get_unknown_404_envelope(self, client):
        resp = await client.get("/api/endpoints/99999")
        assert resp.status_code == 404
        body = resp.json()["error"]
        assert body["code"] == "endpoint_not_found"
        assert "message" in body

    async def test_list_sorted_newest_first(self, client, make_endpoint):
        first = await make_endpoint(name="first")
        await make_endpoint(name="second")
        resp = await client.get("/api/endpoints")
        names = [e["name"] for e in resp.json()["data"]]
        assert names == ["second", "first"] or names[-1] == first["name"]

    async def test_patch_fields(self, client, make_endpoint):
        ep = await make_endpoint(response_status=200)
        resp = await client.patch(
            f"/api/endpoints/{ep['id']}",
            json={
                "name": "renamed",
                "enabled": False,
                "response_status": 500,
                "response_body": '{"broken": true}',
                "response_content_type": "text/plain",
                "response_delay_ms": 100,
                "replay_target_url": "https://target.example.com/hook",
                "max_requests": 55,
                "request_retention_hours": 48,
            },
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "renamed"
        assert data["enabled"] is False
        assert data["status"] == "disabled"
        assert data["response_status"] == 500
        assert data["response_body"] == '{"broken": true}'
        assert data["response_delay_ms"] == 100
        assert data["replay_target_url"] == "https://target.example.com/hook"
        assert data["max_requests"] == 55
        assert data["request_retention_hours"] == 48

    async def test_patch_ttl_extends_expiry(self, client, make_endpoint):
        ep = await make_endpoint(ttl_hours=1)
        old_expiry = ep["expires_at"]
        resp = await client.patch(f"/api/endpoints/{ep['id']}", json={"ttl_hours": 48})
        assert resp.status_code == 200
        assert resp.json()["data"]["expires_at"] > old_expiry

    async def test_patch_signature_rotation(self, client, make_endpoint):
        ep = await make_endpoint(
            signature={
                "enabled": True,
                "header": "X-Signature",
                "algorithm": "hmac-sha256",
                "encoding": "hex",
                "secret": "secret-one",
            }
        )
        assert ep["signature"]["configured"] is True

        resp = await client.get(f"/api/endpoints/{ep['id']}")
        assert "secret-one" not in resp.text  # secret never returned

        # Rotate the secret.
        resp = await client.patch(
            f"/api/endpoints/{ep['id']}",
            json={"signature": {"enabled": True, "header": "X-Signature",
                                "algorithm": "hmac-sha256", "encoding": "hex",
                                "secret": "secret-two"}},
        )
        assert resp.status_code == 200

    async def test_patch_ingest_token_and_removal(self, client, make_endpoint):
        ep = await make_endpoint(ingest_token="tok-abc")
        assert ep["ingest_token_configured"] is True
        assert "tok-abc" not in (await client.get(f"/api/endpoints/{ep['id']}")).text

        resp = await client.patch(
            f"/api/endpoints/{ep['id']}", json={"remove_ingest_token": True}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["ingest_token_configured"] is False

    async def test_delete_endpoint(self, client, make_endpoint):
        ep = await make_endpoint()
        resp = await client.delete(f"/api/endpoints/{ep['id']}")
        assert resp.status_code == 200
        resp = await client.get(f"/api/endpoints/{ep['id']}")
        assert resp.status_code == 404


class TestValidation:
    async def test_blank_name_rejected(self, client):
        resp = await client.post("/api/endpoints", json={"name": "   "})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "invalid_input"

    async def test_bad_ttl_rejected(self, client):
        resp = await client.post("/api/endpoints", json={"name": "x", "ttl_hours": 0})
        assert resp.status_code == 422

    async def test_bad_response_status_rejected(self, client):
        resp = await client.post("/api/endpoints", json={"name": "x", "response_status": 99})
        assert resp.status_code == 422

    async def test_signature_without_secret_rejected(self, client):
        resp = await client.post(
            "/api/endpoints",
            json={"name": "x", "signature": {"enabled": True, "header": "X-Signature"}},
        )
        assert resp.status_code == 422

    async def test_unknown_fields_rejected(self, client):
        resp = await client.post("/api/endpoints", json={"name": "x", "hacker_field": 1})
        assert resp.status_code == 422
