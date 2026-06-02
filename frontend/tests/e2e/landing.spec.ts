import { expect, test } from "@playwright/test";

test("landing page renders the frontend foundation", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /Vinted Monitor dashboard/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /Open dashboard shell/i })).toBeVisible();
  await expect(page.getByText("Phase 1 frontend foundation")).toBeVisible();
  await expect(page.getByText("Monitor command preview")).toBeVisible();
});

test("placeholder app pages stay reachable", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Monitor operations" })).toBeVisible();
  await expect(page.getByText("No backend calls yet")).toBeVisible();

  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Telegram and scraper controls" })).toBeVisible();
  await expect(page.getByText("Token values should stay write-only")).toBeVisible();
});
