import { expect, test } from "@playwright/test";

/**
 * The core loop from the project brief:
 * create endpoint -> send webhook -> inspect -> modify -> replay -> verify.
 */
const ADMIN_TOKEN = process.env.E2E_ADMIN_TOKEN ?? "e2e-admin-token";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(
    (token) => window.localStorage.setItem("webhook-inspector.admin-token", token),
    ADMIN_TOKEN,
  );
});

test("create endpoint, receive webhook, inspect body, replay to mock receiver", async ({
  page,
  request,
}) => {
  // 1. Create an endpoint through the UI.
  await page.goto("/");
  await page.getByRole("button", { name: /new endpoint/i }).click();
  await page.getByLabel("Name").fill("e2e-demo");
  await page.getByRole("button", { name: "Create endpoint" }).click();

  // 2. The endpoint page shows the webhook URL.
  await expect(page.getByText(/Webhook URL/i)).toBeVisible();
  const webhookUrl = (await page.locator(".url-box span").first().textContent())!.trim();
  expect(webhookUrl).toContain("/hook/");

  // 3. Send a real webhook to the captured endpoint.
  const hook = await request.post(webhookUrl, {
    headers: { "Content-Type": "application/json", "X-E2E": "playwright" },
    data: { event: "order.created", order_id: 777, amount: 42.5 },
  });
  expect(hook.status()).toBe(200);

  // 4. The request appears in history (live via SSE or the polling fallback).
  await expect(page.getByRole("cell", { name: "POST" })).toBeVisible();

  // 5. Open the request detail and inspect the JSON body.
  await page.getByRole("cell", { name: "POST" }).click();
  await page.getByRole("tab", { name: "Body" }).click();
  await expect(page.getByText(/order\.created/)).toBeVisible();
  await expect(page.getByText("777")).toBeVisible();

  // 6. Headers were captured, sensitive ones are redacted by default.
  await page.getByRole("tab", { name: "Headers" }).click();
  await expect(page.getByText("x-e2e")).toBeVisible();

  // 7. Replay the captured request (edited) to the dev mock receiver.
  await page.getByRole("tab", { name: "Replay" }).click();
  await page.getByLabel("Target URL").fill(`${process.env.E2E_BASE_URL ?? "http://localhost:8000"}/mock/receiver`);
  await page.getByLabel("Body", { exact: false }).fill(
    JSON.stringify({ event: "order.replayed", order_id: 778 }, null, 2),
  );
  await page.getByRole("button", { name: /send replay/i }).click();

  // 8. The replay result shows a completed HTTP exchange.
  await expect(page.getByText("success", { exact: true })).toBeVisible();
  await expect(page.getByText("200")).toBeVisible();

  // 9. The mock receiver actually received it.
  const history = await request.get("/mock/receiver/requests");
  const received = (await history.json()).data as Array<{ body_text: string }>;
  expect(received[0].body_text).toContain("order.replayed");
});
