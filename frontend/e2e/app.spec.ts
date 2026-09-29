import crypto from "node:crypto";
import { expect, test } from "@playwright/test";

/**
 * The core loop from the project brief, driven through the real UI:
 * create endpoint -> send webhook -> inspect -> search -> modify -> replay.
 *
 * Requires a running stack (docker compose up, or a local backend) with the
 * demo override enabled so replay can target the built-in mock receiver.
 */
const ADMIN_TOKEN = process.env.E2E_ADMIN_TOKEN ?? "ci-e2e-4f9a1c7e2b8d46309a5d1f7c3e6b0a24";
const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8001";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(
    (token) => window.localStorage.setItem("webhook-inspector.admin-token", token),
    ADMIN_TOKEN,
  );
});

test("full loop: create, receive, inspect, search, modify, replay", async ({
  page,
  request,
}) => {
  // 1. Dashboard loads.
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Webhook endpoints" })).toBeVisible();

  // 2. Create an endpoint through the UI.
  await page.getByRole("button", { name: /new endpoint/i }).click();
  await page.getByLabel("Name").fill(`e2e-demo-${Date.now()}`);
  await page.getByRole("button", { name: "Create endpoint" }).click();

  // 3. The endpoint page shows the webhook URL (copyable).
  await expect(page.getByText(/Webhook URL/i)).toBeVisible();
  const webhookUrl = (await page.locator(".url-box span").first().textContent())!.trim();
  expect(webhookUrl).toContain("/hook/");
  await expect(page.getByRole("button", { name: "Copy URL" })).toBeVisible();

  // 4. Send a real webhook + a second one with a distinct marker.
  const hook = await request.post(webhookUrl, {
    headers: { "Content-Type": "application/json", "X-E2E": "playwright" },
    data: { event: "order.created", order_id: 777, amount: 42.5 },
  });
  expect(hook.status()).toBe(200);
  const hook2 = await request.post(webhookUrl, {
    headers: { "Content-Type": "application/json" },
    data: { event: "other.noise", marker: "zz-noise" },
  });
  expect(hook2.status()).toBe(200);

  // 5. Requests appear in history (live via SSE or the polling fallback).
  await expect(page.getByRole("cell", { name: "POST" }).first()).toBeVisible();

  // 6. Search finds the right one.
  await page.getByLabel("Search requests").fill("zz-noise");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText("1 request")).toBeVisible();
  await page.getByLabel("Search requests").fill("");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText("2 requests")).toBeVisible();

  // 7. Open the request detail and inspect the JSON body.
  await page.getByRole("cell", { name: "POST" }).last().click();
  await page.getByRole("tab", { name: "Body" }).click();
  await expect(page.getByText(/order\.created/)).toBeVisible();
  await expect(page.getByText("777")).toBeVisible();

  // 8. Headers were captured.
  await page.getByRole("tab", { name: "Headers" }).click();
  await expect(page.getByText("x-e2e")).toBeVisible();

  // 9. Replay the captured request (edited) to the dev mock receiver.
  await page.getByRole("tab", { name: "Replay" }).click();
  await page.getByLabel("Target URL").fill(`${BASE_URL}/mock/receiver`);
  await page
    .getByLabel("Body")
    .fill(JSON.stringify({ event: "order.replayed", order_id: 778 }, null, 2));
  await page.getByRole("button", { name: /send replay/i }).click();

  // 10. The replay result shows a completed exchange.
  await expect(page.getByText("success", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("200", { exact: true }).first()).toBeVisible();

  // 11. The mock receiver actually received the MODIFIED payload.
  const history = await request.get(`${BASE_URL}/mock/receiver/requests`);
  const received = (await history.json()).data as Array<{ body_text: string }>;
  expect(received[0].body_text).toContain("order.replayed");
  expect(received[0].body_text).toContain("778");
});

test("signature verification is displayed for a signed endpoint", async ({
  page,
  request,
}) => {
  // Create a signed endpoint via the API.
  const secret = "e2e-signing-secret";
  const endpointName = `e2e-signed-${Date.now()}`;
  const created = await request.post(`${BASE_URL}/api/endpoints`, {
    headers: { Authorization: `Bearer ${ADMIN_TOKEN}`, "Content-Type": "application/json" },
    data: {
      name: endpointName,
      signature: {
        enabled: true,
        header: "X-Signature",
        algorithm: "hmac-sha256",
        encoding: "hex",
        secret,
      },
    },
  });
  expect(created.status()).toBe(201);
  const endpoint = (await created.json()).data as { webhook_url: string };

  // Send a correctly signed webhook.
  const body = JSON.stringify({ signed: true, n: 5 });
  const signature = crypto
    .createHmac("sha256", secret)
    .update(body, "utf8")
    .digest("hex");
  const hook = await request.post(endpoint.webhook_url, {
    headers: {
      "Content-Type": "application/json",
      "X-Signature": `sha256=${signature}`,
    },
    data: body,
  });
  expect(hook.status()).toBe(200);

  // Open it in the UI: the verified chip must be visible.
  const endpointId = ((await created.json()).data as { id: number }).id;
  await page.goto(`/endpoints/${endpointId}`);
  await expect(page.getByText("signature verified")).toBeVisible();
});

test("disabled endpoint rejects webhooks with 409", async ({ request }) => {
  const created = await request.post(`${BASE_URL}/api/endpoints`, {
    headers: { Authorization: `Bearer ${ADMIN_TOKEN}`, "Content-Type": "application/json" },
    data: { name: "e2e-disable-me" },
  });
  const endpoint = (await created.json()).data as { id: number; webhook_url: string };
  const patched = await request.patch(`${BASE_URL}/api/endpoints/${endpoint.id}`, {
    headers: { Authorization: `Bearer ${ADMIN_TOKEN}`, "Content-Type": "application/json" },
    data: { enabled: false },
  });
  expect(patched.status()).toBe(200);
  const hook = await request.post(endpoint.webhook_url, { data: { late: true } });
  expect(hook.status()).toBe(409);
  const body = await hook.json();
  expect(body.error.code).toBe("endpoint_disabled");
});
