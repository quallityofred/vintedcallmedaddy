import { expect, test } from "@playwright/test";

test("landing page renders the frontend foundation", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /Vinted Monitor dashboard/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /Open dashboard shell/i })).toBeVisible();
  await expect(page.getByText("Phase 1 frontend foundation")).toBeVisible();
  await expect(page.getByText("Monitor command preview")).toBeVisible();
});

test("placeholder app pages stay reachable", async ({ page }) => {
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

  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Monitor operations" })).toBeVisible();
  await expect(page.getByText("Backend connectivity")).toBeVisible();
  await expect(page.getByText("Reachable")).toBeVisible();
  await expect(page.getByText("Scheduler jobs")).toBeVisible();
  await expect(page.getByText("Scheduler jobs").locator("..").getByText("2", { exact: true })).toBeVisible();

  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Telegram and scraper controls" })).toBeVisible();
  await expect(page.getByText("Token values should stay write-only")).toBeVisible();
});
