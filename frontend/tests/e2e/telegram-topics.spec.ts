import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  // Auth mock
  await page.route("**/api/v1/auth/me*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ user: { id: 1, username: "admin", is_admin: true } }),
    });
  });
});

test("Telegram topics settings work", async ({ page }) => {
  await page.route("**/api/v1/auth/csrf", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ csrf_token: "test-csrf-token" }),
    });
  });

  // Mock settings
  await page.route("**/api/v1/settings", async (route) => {
    await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
            telegram: { token_configured: true, chat_id_configured: true, bot_running: false, token_masked: "...", chat_id_masked: "..." },
            cloudflare_worker: { mode: "auto" }
        }),
    });
  });

  await page.route("**/api/v1/settings/telegram/topics", async (route) => {
    if (route.request().method() === "GET") {
        await route.fulfill({
            contentType: "application/json",
            body: JSON.stringify({
                enabled: false,
                chat_id: "-100123456789",
                auto_create: false,
                recreate_deleted: false,
                fallback_to_main_chat: false,
            }),
        });
    } else {
        await route.fulfill({
            contentType: "application/json",
            body: JSON.stringify({
                enabled: true,
                chat_id: "-100123456789",
                auto_create: true,
                recreate_deleted: true,
                fallback_to_main_chat: true,
            }),
        });
    }
  });

  await page.goto("/settings");
  
  // Wait for loading to finish
  await expect(page.getByText("Telegram Topics")).toBeVisible();
  
  // Enable
  await page.getByRole("checkbox", { name: "Enable Telegram Topics" }).check();

  // Save
  await page.locator('#saveTopicSettings').click();

  await expect(page.getByText("Topic settings updated")).toBeVisible();
});

test("Verify group shows actionable error", async ({ page }) => {
  await page.route("**/api/v1/auth/csrf", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ csrf_token: "test-csrf-token" }),
    });
  });

  await page.route("**/api/v1/settings/telegram/topics", async (route) => {
    await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
            enabled: false,
            chat_id: "",
            auto_create: true,
            recreate_deleted: false,
            fallback_to_main_chat: false,
        }),
    });
  });

  await page.route("**/api/v1/settings/telegram/topics/verify-group", async (route) => {
    await route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ detail: "This Telegram group does not have topics enabled." }),
    });
  });

  await page.goto("/settings");
  await page.locator('#verifyTopicGroup').click();

  await expect(page.getByText("This Telegram group does not have topics enabled")).toBeVisible({ timeout: 10000 });
});

test("monitors page batches Telegram topic status loading", async ({ page }) => {
  let settingsCalls = 0;
  let batchCalls = 0;
  let perMonitorTopicCalls = 0;

  const monitors = Array.from({ length: 20 }, (_, index) => ({
    id: index + 1,
    name: `Monitor ${index + 1}`,
    original_url: `https://www.vinted.fr/catalog?search_text=item${index + 1}`,
    interval_sec: 120,
    is_active: true,
    last_check_at: null,
    items_found_count: 0,
    domains: ["vinted.fr"],
  }));

  await page.route("**/api/v1/settings/telegram/topics", async (route) => {
    settingsCalls += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        enabled: true,
        chat_configured: true,
        chat_id_masked: "******6789",
        auto_create: true,
        recreate_deleted: false,
        fallback_to_main_chat: false,
        status: "not_verified",
        message: null,
      }),
    });
  });

  await page.route("**/api/v1/monitors/telegram-topics", async (route) => {
    batchCalls += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        topics_enabled: true,
        topics: {
          "1": {
            monitor_id: 1,
            status: "active",
            topic_name: "Monitor 1",
            message_thread_id_masked: "******4321",
            last_error: null,
            last_error_code: null,
            updated_at: "2026-06-05T00:00:00Z",
          },
        },
      }),
    });
  });

  await page.route(/\/api\/v1\/monitors\/\d+\/telegram-topic$/, async (route) => {
    perMonitorTopicCalls += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ monitor_id: 1, enabled: true, topic: null }),
    });
  });

  await page.route("**/api/v1/monitors", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(monitors),
    });
  });

  await page.goto("/monitors");

  await expect(page.getByText("Monitor 1").first()).toBeVisible();
  await expect(page.getByText("Monitor 20")).toBeVisible();
  await expect(page.getByText("Topic: Monitor 1")).toBeVisible();
  await expect(page.getByText("not_created").first()).toBeVisible();

  expect(settingsCalls).toBe(1);
  expect(batchCalls).toBe(1);
  expect(perMonitorTopicCalls).toBe(0);
});
