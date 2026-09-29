"""Request history: pagination, ordering, search filters, deletion."""

import json


async def seed_requests(client, ep, count: int, prefix="item") -> None:
    for i in range(count):
        resp = await client.post(
            ep["webhook_url"],
            content=json.dumps({"needle": f"{prefix}-{i}"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200


class TestPagination:
    async def test_pagination_and_ordering(self, client, make_endpoint):
        ep = await make_endpoint()
        await seed_requests(client, ep, 25)

        page1 = (await client.get(f"/api/endpoints/{ep['id']}/requests?page_size=10")).json()[
            "data"
        ]
        assert page1["total"] == 25
        assert len(page1["items"]) == 10
        assert page1["page"] == 1
        assert page1["page_size"] == 10

        ids = [item["id"] for item in page1["items"]]
        assert ids == sorted(ids, reverse=True)  # newest first

        page3 = (
            await client.get(f"/api/endpoints/{ep['id']}/requests?page=3&page_size=10")
        ).json()["data"]
        assert len(page3["items"]) == 5

        all_ids = {item["id"] for page in (page1, page3) for item in page["items"]}
        assert len(all_ids) == 15  # pages don't overlap

    async def test_page_beyond_range_empty(self, client, make_endpoint):
        ep = await make_endpoint()
        await seed_requests(client, ep, 3)
        data = (await client.get(f"/api/endpoints/{ep['id']}/requests?page=99")).json()["data"]
        assert data["items"] == []
        assert data["total"] == 3

    async def test_unknown_endpoint_404(self, client):
        resp = await client.get("/api/endpoints/31337/requests")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "endpoint_not_found"


class TestSearch:
    async def test_search_body_content(self, client, make_endpoint):
        ep = await make_endpoint()
        await seed_requests(client, ep, 10)
        resp = await client.get(f"/api/endpoints/{ep['id']}/requests?search=item-7")
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["body_size"] > 0

    async def test_search_no_results(self, client, make_endpoint):
        ep = await make_endpoint()
        await seed_requests(client, ep, 3)
        resp = await client.get(f"/api/endpoints/{ep['id']}/requests?search=does-not-exist")
        assert resp.json()["data"]["total"] == 0

    async def test_search_header_value(self, client, make_endpoint):
        ep = await make_endpoint()
        await seed_requests(client, ep, 3)
        await client.post(ep["webhook_url"], headers={"X-Trace-Id": "findme-42"}, content=b"x")
        resp = await client.get(f"/api/endpoints/{ep['id']}/requests?search=findme-42")
        assert resp.json()["data"]["total"] == 1

    async def test_search_path(self, client, make_endpoint):
        ep = await make_endpoint()
        await seed_requests(client, ep, 2)
        # All requests share /hook/<public_id>; searching the id must match.
        resp = await client.get(f"/api/endpoints/{ep['id']}/requests?search={ep['public_id'][:8]}")
        assert resp.json()["data"]["total"] == 2

    async def test_filter_by_method(self, client, make_endpoint):
        ep = await make_endpoint()
        await seed_requests(client, ep, 2)
        await client.get(ep["webhook_url"])
        await client.put(ep["webhook_url"], content=b"x")
        resp = await client.get(f"/api/endpoints/{ep['id']}/requests?method=get")
        assert resp.json()["data"]["total"] == 1
        assert resp.json()["data"]["items"][0]["method"] == "GET"

    async def test_date_range_filter(self, client, make_endpoint):
        from datetime import timedelta

        ep = await make_endpoint()
        await seed_requests(client, ep, 5)
        future = (await _server_now(client)) + timedelta(hours=1)
        past = (await _server_now(client)) - timedelta(hours=24)
        # Pass datetimes as encoded params: a raw "+" in the query string would
        # be decoded as a space and fail datetime parsing.
        resp = await client.get(
            f"/api/endpoints/{ep['id']}/requests",
            params={"date_from": future.isoformat()},
        )
        assert resp.json()["data"]["total"] == 0
        resp = await client.get(
            f"/api/endpoints/{ep['id']}/requests",
            params={"date_from": past.isoformat()},
        )
        assert resp.json()["data"]["total"] == 5

    async def test_combined_filters(self, client, make_endpoint):
        ep = await make_endpoint()
        await seed_requests(client, ep, 5)
        await client.post(
            ep["webhook_url"],
            content=b'{"needle": "special-get"}',
            headers={"Content-Type": "application/json"},
        )
        # A GET cannot be searched by body since GETs carry no body here; combine
        # method + search instead.
        resp = await client.get(f"/api/endpoints/{ep['id']}/requests?method=POST&search=item-3")
        data = resp.json()["data"]
        assert data["total"] == 1


class TestDeletion:
    async def test_delete_single_request(self, client, make_endpoint):
        ep = await make_endpoint()
        await seed_requests(client, ep, 2)
        lst = (await client.get(f"/api/endpoints/{ep['id']}/requests")).json()["data"]
        request_id = lst["items"][0]["id"]
        resp = await client.delete(f"/api/requests/{request_id}")
        assert resp.status_code == 200
        resp = await client.get(f"/api/requests/{request_id}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "request_not_found"

    async def test_clear_history(self, client, make_endpoint):
        ep = await make_endpoint()
        await seed_requests(client, ep, 6)
        resp = await client.delete(f"/api/endpoints/{ep['id']}/requests")
        assert resp.status_code == 200
        assert resp.json()["data"]["count"] == 6
        data = (await client.get(f"/api/endpoints/{ep['id']}/requests")).json()["data"]
        assert data["total"] == 0

    async def test_delete_unknown_request_404(self, client):
        resp = await client.delete("/api/requests/424242")
        assert resp.status_code == 404


async def _server_now(client) -> object:
    from datetime import datetime

    ep = (await client.post("/api/endpoints", json={"name": "clock"})).json()["data"]
    return datetime.fromisoformat(ep["created_at"].replace("Z", "+00:00"))
