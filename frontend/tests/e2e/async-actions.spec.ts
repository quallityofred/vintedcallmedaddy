import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/auth/me*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ user: { id: 1, username: "admin", is_admin: true } }),
    });
  });

  await page.route("**/api/v1/auth/csrf", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ csrf_token: "test-csrf-token" }),
    });
  });
});

test("monitor action loading is keyed per monitor action", async ({ page }) => {
  const monitors = [
    {
      id: 1,
      name: "Nike search",
      original_url: "https://www.vinted.fr/catalog?search_text=nike",
      interval_sec: 120,
      is_active: true,
      last_check_at: null,
      items_found_count: 2,
      domains: ["vinted.fr"],
    },
    {
      id: 2,
      name: "Adidas search",
      original_url: "https://www.vinted.de/catalog?search_text=adidas",
      interval_sec: 180,
      is_active: true,
      last_check_at: null,
      items_found_count: 0,
      domains: ["vinted.de"],
    },
  ];

  let releasePause: (() => void) | null = null;
  let releaseCheck: (() => void) | null = null;

  await page.route("**/api/v1/settings/telegram/topics", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ enabled: false, auto_create: true, recreate_deleted: false, fallback_to_main_chat: false }),
    });
  });
  await page.route("**/api/v1/monitors/telegram-topics", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ topics_enabled: false, topics: {} }) });
  });
  await page.route("**/api/v1/monitors/1/pause", async (route) => {
    expect(route.request().headers()["x-csrf-token"]).toBe("test-csrf-token");
    await new Promise<void>((resolve) => {
      releasePause = resolve;
    });
    monitors[0] = { ...monitors[0], is_active: false };
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(monitors[0]) });
  });
  await page.route("**/api/v1/monitors/2/check-now", async (route) => {
    expect(route.request().headers()["x-csrf-token"]).toBe("test-csrf-token");
    await new Promise<void>((resolve) => {
      releaseCheck = resolve;
    });
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ok: true, code: "triggered", message: "Check started.", retry_after: 30 }),
    });
  });
  await page.route("**/api/v1/monitors", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(monitors) });
  });

  await page.goto("/monitors");
  await expect(page.getByText("Nike search")).toBeVisible();
  await expect(page.getByText("Adidas search")).toBeVisible();

  const pauseNike = page.getByRole("button", { name: "Pause monitor Nike search" });
  const checkAdidas = page.getByRole("button", { name: "Run monitor check for Adidas search" });

  await pauseNike.click();
  await expect(pauseNike).toBeDisabled();
  await expect(pauseNike).toContainText("Pause");

  await checkAdidas.click();
  await expect(checkAdidas).toBeDisabled();
  await expect(pauseNike).toBeDisabled();

  releaseCheck?.();
  await expect(checkAdidas).toBeEnabled();
  await expect(pauseNike).toBeDisabled();

  releasePause?.();
  await expect(page.getByRole("button", { name: "Resume monitor Nike search" })).toBeVisible();
  await expect(page.getByText("Paused", { exact: true })).toBeVisible();
});

test("check-now reports an actionable CSRF rejection", async ({ page }) => {
  const monitors = [
    {
      id: 3,
      name: "Protected monitor",
      original_url: "https://www.vinted.pl/catalog?search_text=nike",
      interval_sec: 120,
      is_active: true,
      last_check_at: null,
      items_found_count: 0,
      domains: ["vinted.pl"],
    },
  ];
  await page.route("**/api/v1/settings/telegram/topics", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ enabled: false }) });
  });
  await page.route("**/api/v1/monitors/telegram-topics", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ topics_enabled: false, topics: {} }) });
  });
  await page.route("**/api/v1/monitors/3/check-now", async (route) => {
    expect(route.request().headers()["x-csrf-token"]).toBe("test-csrf-token");
    await route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Invalid CSRF token" }),
    });
  });
  await page.route("**/api/v1/monitors", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(monitors) });
  });

  await page.goto("/monitors");
  await page.getByRole("button", { name: "Run monitor check for Protected monitor" }).click();
  await expect(page.getByText("Action rejected by CSRF/auth; refresh the page and try again through the UI.")).toBeVisible();
});

test("settings topic verify and save keep independent loading states", async ({ page }) => {
  let releaseVerify: (() => void) | null = null;
  let releaseSave: (() => void) | null = null;

  await page.route("**/api/v1/settings", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        telegram: { token_configured: true, chat_id_configured: true, bot_running: false, token_masked: "...", chat_id_masked: "..." },
        cloudflare_worker: { mode: "auto" },
      }),
    });
  });
  await page.route("**/api/v1/settings/telegram/topics", async (route) => {
    if (route.request().method() === "PATCH") {
      await new Promise<void>((resolve) => {
        releaseSave = resolve;
      });
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        enabled: true,
        chat_id: "-100123456789",
        auto_create: true,
        recreate_deleted: false,
        fallback_to_main_chat: false,
      }),
    });
  });
  await page.route("**/api/v1/settings/telegram/topics/verify-group", async (route) => {
    await new Promise<void>((resolve) => {
      releaseVerify = resolve;
    });
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ok: true, success: true, message: "Bot can create topics in this group." }),
    });
  });

  await page.goto("/settings");
  await expect(page.getByText("Telegram Topics")).toBeVisible();

  const verify = page.locator("#verifyTopicGroup");
  const save = page.locator("#saveTopicSettings");
  await verify.click();
  await expect(verify).toContainText("Verifying");
  await expect(save).toBeEnabled();

  await save.click();
  await expect(save).toContainText("Saving");
  await expect(verify).toContainText("Verifying");

  releaseSave?.();
  await expect(save).toContainText("Save settings");
  await expect(verify).toContainText("Verifying");

  releaseVerify?.();
  await expect(verify).toContainText("Verify group");
  await expect(page.getByRole("main").getByText("Bot can create topics in this group.")).toBeVisible();
});

test("recent item hide seller loading is scoped per seller", async ({ page }) => {
  let releaseFirstHide: (() => void) | null = null;

  await page.route("**/api/health", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ status: "ok" }) });
  });
  await page.route("**/api/v1/dashboard/stats", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        active_monitors_count: 1,
        paused_monitors_count: 0,
        items_today_count: 2,
        total_items_count: 2,
        last_found_at: null,
        telegram_status: { configured: false, running: false },
      }),
    });
  });
  await page.route("**/api/v1/system/status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ scheduler_running: true, active_jobs_count: 1, bots_running_count: 0, database_status: "ok" }),
    });
  });
  await page.route("**/api/v1/items?**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          { id: 1, title: "First item", price: 10, currency: "EUR", brand: "A", size: "", condition: "", item_url: "https://example.test/1", seller_id: 101, found_at: "2026-06-05T00:00:00Z" },
          { id: 2, title: "Second item", price: 12, currency: "EUR", brand: "B", size: "", condition: "", item_url: "https://example.test/2", seller_id: 202, found_at: "2026-06-05T00:00:00Z" },
        ],
        limit: 10,
        offset: 0,
        total: 2,
      }),
    });
  });
  await page.route("**/api/v1/hidden-sellers", async (route) => {
    const sellerId = (route.request().postDataJSON() as { seller_id: number }).seller_id;
    if (sellerId === 101) {
      await new Promise<void>((resolve) => {
        releaseFirstHide = resolve;
      });
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ seller_id: sellerId, hidden_at: "2026-06-05T00:00:00Z" }),
    });
  });

  await page.goto("/dashboard");
  await expect(page.getByText("First item")).toBeVisible();
  await expect(page.getByText("Second item")).toBeVisible();

  const firstHide = page.getByRole("button", { name: "Hide seller 101" });
  const secondHide = page.getByRole("button", { name: "Hide seller 202" });
  await firstHide.click();
  await expect(firstHide).toBeDisabled();
  await expect(secondHide).toBeEnabled();

  await secondHide.click();
  await expect(page.getByText("Second item")).toHaveCount(0);
  await expect(firstHide).toBeDisabled();

  releaseFirstHide?.();
  await expect(page.getByText("First item")).toHaveCount(0);
});
