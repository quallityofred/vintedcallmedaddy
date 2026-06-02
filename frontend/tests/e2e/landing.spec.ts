import { expect, test } from "@playwright/test";

test("landing page renders the frontend foundation", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /Vinted Monitor dashboard/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /Open dashboard shell/i })).toBeVisible();
  await expect(page.getByText("Phase 1 frontend foundation")).toBeVisible();
});
