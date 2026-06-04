import { expect, test } from "@playwright/test";

test("landing page renders the frontend foundation", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /Vinted Monitor dashboard/i })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
  await expect(page.getByText("Live monitoring console")).toBeVisible();
  await expect(page.getByText("Product overview")).toBeVisible();
  await expect(page.getByRole("button", { name: /New monitor/i })).toHaveCount(0);
});

test("protected pages redirect unauthenticated users to login with next", async ({ page }) => {
  await page.route("**/api/v1/auth/me*", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Not authenticated" }),
    });
  });

  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login\?next=%2Fdashboard$/);
  await expect(page.getByRole("heading", { name: "Monitor operations" })).toHaveCount(0);

  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings$/);
  await expect(page.getByRole("heading", { name: "Telegram Controls" })).toHaveCount(0);

  await page.goto("/monitors");
  await expect(page).toHaveURL(/\/login\?next=%2Fmonitors$/);
  await expect(page.getByRole("heading", { name: "Manage your Vinted search monitors" })).toHaveCount(0);

  await page.goto("/admin");
  await expect(page).toHaveURL(/\/login\?next=%2Fadmin$/);
  await expect(page.getByRole("heading", { name: "Administration" })).toHaveCount(0);
});

test("authenticated app pages stay reachable", async ({ page }) => {
  await page.route("**/api/v1/auth/me*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ user: { id: 1, username: "admin", is_admin: true } }),
    });
  });

  await page.route("**/api/health", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        status: "ok",
        scheduler_jobs: 2,
        bots_running: 1,
      }),
    });
  });
  await page.route("**/api/v1/dashboard/stats", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        active_monitors_count: 1,
        paused_monitors_count: 1,
        items_today_count: 2,
        total_items_count: 5,
        last_found_at: null,
        telegram_status: { configured: true, running: false },
      }),
    });
  });
  await page.route("**/api/v1/system/status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        scheduler_running: true,
        active_jobs_count: 1,
        bots_running_count: 0,
        database_status: "ok",
      }),
    });
  });
  await page.route("**/api/v1/monitors", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: 1,
          name: "Nike search",
          original_url: "https://www.vinted.fr/catalog?search_text=nike",
          interval_sec: 120,
          is_active: true,
          last_check_at: null,
          items_found_count: 2,
        },
        {
          id: 2,
          name: "Adidas search",
          original_url: "https://www.vinted.de/catalog?search_text=adidas",
          interval_sec: 180,
          is_active: false,
          last_check_at: null,
          items_found_count: 0,
        },
      ]),
    });
  });
  await page.route("**/api/v1/monitors/domains", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        { domain: "vinted.fr", flag: "FR" },
        { domain: "vinted.de", flag: "DE" },
      ]),
    });
  });
  await page.route("**/api/v1/items?**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], limit: 20, offset: 0, total: 0 }),
    });
  });
  await page.route("**/api/v1/telegram/status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        telegram: {
          token_configured: true,
          token_masked: "******1234",
          chat_id_configured: true,
          chat_id_masked: "******4321",
          bot_running: false,
        },
      }),
    });
  });
  await page.route("**/api/v1/admin/invites", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Monitor operations" })).toBeVisible();
  await expect(page.getByText("Backend connectivity")).toBeVisible();
  await expect(page.getByText("Reachable")).toBeVisible();
  await expect(page.getByText("Jobs", { exact: true })).toBeVisible();
  await expect(page.getByText("Jobs", { exact: true }).locator("..").getByText("2", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /Manage monitors/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /New monitor/i })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Monitors", exact: true })).toBeVisible();

  await page.getByRole("link", { name: /Manage monitors/i }).click();
  await expect(page).toHaveURL(/\/monitors$/);
  await expect(page.getByRole("heading", { name: "Manage your Vinted search monitors" })).toBeVisible();
  await expect(page.getByText("Nike search")).toBeVisible();
  await page.getByLabel("Select all monitors").check();
  await expect(page.getByRole("button", { name: /Delete 2 selected monitors/i })).toBeVisible();
  await page.getByRole("button", { name: /New monitor/i }).click();
  await expect(page.getByRole("heading", { name: "Create monitor" })).toBeVisible();
  await expect(page.getByText("Target Domains (0 / 2)")).toBeVisible();

  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Configuration" })).toBeVisible();
  await expect(page.getByText("Tokens are write-only")).toBeVisible();

  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  await expect(page.getByText("Invite Management")).toBeVisible();
});

test("dashboard and monitors stay within the mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });

  await page.route("**/api/v1/auth/me*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ user: { id: 1, username: "user", is_admin: false } }),
    });
  });
  await page.route("**/api/health", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ status: "ok", scheduler_jobs: 1, bots_running: 0 }),
    });
  });
  await page.route("**/api/v1/dashboard/stats", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        active_monitors_count: 1,
        paused_monitors_count: 1,
        items_today_count: 0,
        total_items_count: 2,
        last_found_at: null,
        telegram_status: { configured: true, running: false },
      }),
    });
  });
  await page.route("**/api/v1/system/status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        scheduler_running: true,
        active_jobs_count: 1,
        bots_running_count: 0,
        database_status: "ok",
      }),
    });
  });
  await page.route("**/api/v1/items?**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], limit: 20, offset: 0, total: 0 }),
    });
  });
  await page.route("**/api/v1/monitors", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: 1,
          name: "Nike search",
          original_url: "https://www.vinted.fr/catalog?search_text=nike",
          interval_sec: 120,
          is_active: true,
          last_check_at: null,
          items_found_count: 2,
        },
      ]),
    });
  });
  await page.route("**/api/v1/monitors/domains", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([{ domain: "vinted.fr", flag: "FR" }]),
    });
  });

  await page.goto("/dashboard");
  await expect(page.getByRole("link", { name: /Manage monitors/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /New monitor/i })).toHaveCount(0);
  await expect(page.locator("html")).toHaveJSProperty("scrollWidth", 390);

  await page.getByRole("link", { name: /Manage monitors/i }).click();
  await expect(page).toHaveURL(/\/monitors$/);
  await expect(page.getByText("Nike search")).toBeVisible();
  await expect(page.locator("html")).toHaveJSProperty("scrollWidth", 390);
});

test("login page posts credentials and shows safe API errors", async ({ page }) => {
  await page.route("**/api/v1/auth/csrf", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ csrf_token: "test-csrf-token" }),
    });
  });

  await page.route("**/api/v1/auth/login", async (route) => {
    const request = route.request();
    expect(request.method()).toBe("POST");
    expect(request.headers()["x-csrf-token"]).toBe("test-csrf-token");
    expect(request.postDataJSON()).toEqual({
      username: "wrong-user",
      password: "wrong-password",
    });

    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Invalid username or password" }),
    });
  });

  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();

  await page.getByLabel("Username").fill("wrong-user");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "Invalid username or password." })).toBeVisible();
});

test("login and register respect next redirect", async ({ page }) => {
  await page.route("**/api/v1/auth/csrf", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ csrf_token: "test-csrf-token" }),
    });
  });

  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        user: { id: 1, username: "user", is_admin: false },
        csrf_token: "session-csrf",
      }),
    });
  });

  await page.goto("/login?next=/settings");
  await page.getByLabel("Username").fill("user");
  await page.getByLabel("Password").fill("password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/settings$/);

  await page.route("**/api/v1/auth/register", async (route) => {
    expect(route.request().postDataJSON()).toMatchObject({
      username: "new-user",
      password_confirm: "password",
      invite_code: "invite-code",
    });
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        user: { id: 2, username: "new-user", is_admin: false },
        csrf_token: "session-csrf",
      }),
    });
  });

  await page.goto("/register?next=/dashboard");
  await page.getByLabel("Username").fill("new-user");
  await page.getByLabel("Invite code").fill("invite-code");
  await page.getByLabel("Password", { exact: true }).fill("password");
  await page.getByLabel("Confirm password").fill("password");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("non-admin users cannot see admin content", async ({ page }) => {
  await page.route("**/api/v1/auth/me*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ user: { id: 1, username: "user", is_admin: false } }),
    });
  });
  await page.route("**/api/health", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ status: "ok" }) });
  });
  await page.route("**/api/v1/dashboard/stats", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        active_monitors_count: 0,
        paused_monitors_count: 0,
        items_today_count: 0,
        total_items_count: 0,
        last_found_at: null,
        telegram_status: { configured: false, running: false },
      }),
    });
  });
  await page.route("**/api/v1/system/status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        scheduler_running: true,
        active_jobs_count: 0,
        bots_running_count: 0,
        database_status: "ok",
      }),
    });
  });
  await page.route("**/api/v1/items?**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items: [], limit: 20, offset: 0, total: 0 }),
    });
  });

  await page.goto("/admin");
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("link", { name: "Monitors", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Administration" })).toHaveCount(0);
});
