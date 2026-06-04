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
                telegram_topics_enabled: false,
                telegram_topics_chat_id: "-100123456789",
                telegram_topics_auto_create: false,
                telegram_topics_recreate_deleted: false,
                telegram_topics_fallback_to_main_chat: false,
            }),
        });
    } else {
        await route.fulfill({
            contentType: "application/json",
            body: JSON.stringify({
                telegram_topics_enabled: true,
                telegram_topics_chat_id: "-100123456789",
                telegram_topics_auto_create: true,
                telegram_topics_recreate_deleted: true,
                telegram_topics_fallback_to_main_chat: true,
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
  await page.route("**/api/v1/settings/telegram/topics", async (route) => {
    await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
            telegram_topics_enabled: false,
            telegram_topics_chat_id: "",
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
