import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("publisher completes an offline illustrated edition in the browser", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page
    .getByLabel("Email address")
    .fill(`browser-${randomUUID()}@example.org`);
  await page.getByLabel("Password").fill(randomUUID() + randomUUID());
  await page
    .getByRole("button", { name: "Create your studio", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "A library of possibilities." }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/dashboard-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Create a book", exact: true })
    .first()
    .click();
  await page.getByLabel("Book title", { exact: true }).fill("Ivanhoe");
  await page
    .getByLabel("Original author", { exact: true })
    .fill("Sir Walter Scott");
  await page.locator("input[type=file]").setInputFiles({
    name: "ivanhoe.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "CHAPTER I\n" +
        "Ivanhoe rode to the castle. Rebecca tended his wounds. ".repeat(12),
    ),
  });
  await page.getByRole("checkbox").check();
  await page
    .getByLabel("Publishing rights declaration")
    .fill("Public domain in the United States; source is Sir Walter Scott.");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByLabel("Pages per original chapter").fill("2");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Create my book" }).click();
  await expect(
    page.getByRole("heading", { name: "Ivanhoe", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Analyze manuscript" }).click();
  await expect(page.locator(".job-info strong")).toHaveText(
    "generate character references",
    { timeout: 30000 },
  );
  await expect(page.locator(".job-info .badge")).toHaveText("review");
  await page.locator(".chapter-card>summary").click();
  await page.getByRole("button", { name: "Approve summary" }).click();
  await page
    .getByRole("button", { name: "Authorize batch & continue" })
    .click();
  await expect(page.locator(".job-info strong")).toHaveText("plan pages", {
    timeout: 30000,
  });
  await expect(page.locator(".job-info .badge")).toHaveText("review");
  await page.getByRole("tab", { name: /Character Studio/ }).click();
  await expect(page.locator(".character-card")).toHaveCount(2);
  for (const name of ["Ivanhoe", "Rebecca"]) {
    await page
      .locator(".character-card")
      .filter({ has: page.getByRole("heading", { name, exact: true }) })
      .click();
    await page
      .getByRole("button", { name: "Approve & lock this reference" })
      .click();
    await expect(
      page.getByText(
        "This design is canonical. Page regeneration preserves it.",
      ),
    ).toBeVisible();
    await page.getByRole("button", { name: "Close character" }).click();
  }
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.locator(".job-info strong")).toHaveText(
    "generate page art",
    { timeout: 30000 },
  );
  await page.getByRole("tab", { name: "Book Editor" }).click();
  await expect(
    page.locator(".page-tree .tree-chapter>button:not(.insert-page)"),
  ).toHaveCount(2);
  for (let i = 0; i < 2; i++) {
    await page
      .locator(".page-tree .tree-chapter>button:not(.insert-page)")
      .nth(i)
      .click();
    await page
      .getByRole("button", { name: "Approve script", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Generate art", exact: true }),
    ).toBeEnabled();
  }
  await page
    .getByRole("button", { name: "Authorize batch & continue" })
    .click();
  await expect(page.locator(".job-info strong")).toHaveText("export pdf", {
    timeout: 30000,
  });
  await expect(page.locator(".page-canvas>img")).toBeVisible();
  for (let i = 0; i < 2; i++) {
    await page
      .locator(".page-tree .tree-chapter>button:not(.insert-page)")
      .nth(i)
      .click();
    await page.getByLabel("Approve this page").check();
    await page
      .getByRole("button", { name: "Save changes", exact: true })
      .click();
    await expect(page.locator(".canvas-foot .badge")).toHaveText("Approved");
  }
  await page.getByRole("button", { name: "Facing pages" }).click();
  await page.screenshot({
    path: "test-results/editor-desktop.png",
    fullPage: true,
  });
  await page.getByRole("tab", { name: "Cover & print" }).click();
  await page.getByRole("button", { name: "Generate cover art" }).click();
  await expect(page.locator(".cover-preview>img")).toBeVisible({
    timeout: 30000,
  });
  await page.getByLabel("Approve cover artwork").check();
  await page.getByRole("button", { name: "Save cover", exact: true }).click();
  await page.getByRole("tab", { name: "Exports", exact: true }).click();
  await page.getByRole("button", { name: "Create export package" }).click();
  await expect(
    page.getByText("Proof · review required", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("OFFLINE TEST ART: these proofs must not be published"),
  ).toBeVisible();
  const download = page.getByRole("link", { name: /Complete package/ });
  const result = await page.request.get((await download.getAttribute("href"))!);
  expect(result.status()).toBe(200);
  expect(result.headers()["content-type"]).toContain("zip");
  await page.reload();
  await page
    .getByRole("button", { name: "Ivanhoe", exact: false })
    .filter({
      has: page.getByRole("heading", { name: "Ivanhoe", exact: true }),
    })
    .click();
  await page.getByRole("tab", { name: "Character Studio" }).click();
  await expect(
    page.locator(".character-card .badge").filter({ hasText: "Canonical" }),
  ).toHaveCount(2);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "My Books" }).click();
  await expect(
    page.getByRole("heading", { name: "A library of possibilities." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/dashboard-mobile.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Ivanhoe", exact: false })
    .filter({
      has: page.getByRole("heading", { name: "Ivanhoe", exact: true }),
    })
    .click();
  await page.getByRole("tab", { name: "Book Editor" }).click();
  for (const remaining of [1, 0]) {
    page.once("dialog", (dialog) => dialog.accept());
    await page
      .getByRole("button", { name: "Delete page", exact: true })
      .click();
    await expect(
      page.locator(".page-tree .tree-chapter>button:not(.insert-page)"),
    ).toHaveCount(remaining);
  }
  await expect(
    page.getByRole("heading", { name: "A blank canvas, for now." }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Insert a page", exact: true })
    .click();
  await expect(
    page.locator(".page-tree .tree-chapter>button:not(.insert-page)"),
  ).toHaveCount(1);
  expect(errors).toEqual([]);
});
