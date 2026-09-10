import { expect, test } from "@playwright/test";

// Must track the mock IMAP server started by playwright.config.ts.
const IMAP_PORT = process.env.HYMAIL_E2E_IMAP_PORT ?? "11430";

test("v0.0.1 account setup and sync demo path", async ({ page }) => {
  await page.goto("/setup");

  await page.getByPlaceholder("you@example.com").fill("user@example.com");
  await page.getByRole("combobox").selectOption("custom");
  await page.getByPlaceholder("imap.example.com").fill("127.0.0.1");
  await page.getByPlaceholder("993").fill(IMAP_PORT);
  await page.getByRole("checkbox").uncheck();
  await page.getByPlaceholder("IMAP 授权码").fill("secret");

  await page.getByRole("button", { name: "测试连接" }).click();
  await expect(page.getByText("连接测试成功")).toBeVisible();

  await page.getByRole("button", { name: "保存账号" }).click();
  await expect(page.getByText("账号已保存")).toBeVisible();

  await page.getByRole("link", { name: "邮件" }).click();
  await page.getByRole("button", { name: /INBOX/ }).click();
  await page.getByRole("button", { name: "同步", exact: true }).click();

  await expect(page.getByTestId("mail-sync-last-uid")).toHaveText(
    "last UID: 3",
    { timeout: 15_000 },
  );
  await expect(page.getByTestId("mail-sync-state")).toHaveText("IDLE");

  await expect(page.getByText("E2E One")).toBeVisible();
  await expect(page.getByText("E2E Two")).toBeVisible();

  // An HTML message must render in a sandboxed frame: its own styles apply
  // inside, but must never reach the app document.
  await page.getByRole("button", { name: /E2E HTML/ }).click();
  const frame = page.frameLocator('[data-testid="message-body-frame"]');
  await expect(frame.locator("body")).toHaveCSS(
    "font-family",
    /Comic Sans MS/,
  );
  const appFontFamily = await page.evaluate(
    () => getComputedStyle(document.body).fontFamily,
  );
  expect(appFontFamily).not.toMatch(/Comic Sans/i);

  await page.getByTestId("mail-sync-detail-toggle").click();
  await expect(page.getByText("同步事件时间线")).toBeVisible();
  await expect(page.getByText("sync.completed")).toBeVisible();
});

test("theme toggle switches the shell and survives a reload", async ({
  page,
}) => {
  // The shell renders even without an account, so /setup is enough to reach
  // the sidebar toggle.
  await page.goto("/setup");

  const html = page.locator("html");
  const toggle = page.getByTestId("theme-toggle");
  const shell = page.locator("main");
  const darkCanvas = "rgb(13, 17, 23)"; // GitHub canvas #0d1117

  await expect(html).not.toHaveClass(/dark/);
  await expect(toggle).toHaveAccessibleName("切换到夜间模式");
  // Tailwind v4 ships its palette in oklch, so the light value is not rgb().
  expect(
    await shell.evaluate((el) => getComputedStyle(el).backgroundColor),
  ).not.toBe(darkCanvas);

  await toggle.click();

  await expect(html).toHaveClass(/dark/);
  await expect(toggle).toHaveAccessibleName("切换到日间模式");
  await expect(shell).toHaveCSS("background-color", darkCanvas);

  // The inline script in index.html must restore it before first paint.
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.locator("main")).toHaveCSS(
    "background-color",
    darkCanvas,
  );
});

test("sync all folders in one click", async ({ page }) => {
  // Self-contained: each test gets a fresh browser context, so the account has
  // to be configured again even though the database is shared.
  await page.goto("/setup");
  await page.getByPlaceholder("you@example.com").fill("user@example.com");
  await page.getByRole("combobox").selectOption("custom");
  await page.getByPlaceholder("imap.example.com").fill("127.0.0.1");
  await page.getByPlaceholder("993").fill(IMAP_PORT);
  await page.getByRole("checkbox").uncheck();
  await page.getByPlaceholder("IMAP 授权码").fill("secret");
  await page.getByRole("button", { name: "保存账号" }).click();
  await expect(page.getByText("账号已保存")).toBeVisible();

  await page.getByRole("link", { name: "邮件" }).click();
  await page.getByRole("button", { name: "刷新文件夹" }).click();

  await page.getByTestId("mail-sync-all").click();

  const progress = page.getByTestId("mail-batch-progress");
  await expect(progress).toBeVisible();
  // Two mailboxes carry mail in the mock: INBOX and Sent.
  await expect(progress).toContainText("同步全部 2/2", { timeout: 20_000 });
  await expect(page.getByTestId("mail-batch-current")).toHaveText("已完成");

  // The queue view reports the individual jobs. The database is shared with
  // earlier tests, so assert on content rather than an exact row count.
  await page.getByTestId("mail-sync-detail-toggle").click();
  await expect(page.getByText("同步队列")).toBeVisible();
  const rows = page.getByTestId("sync-job-row");
  await expect(rows.filter({ hasText: "INBOX" }).first()).toContainText(
    "已完成",
  );
  await expect(rows.filter({ hasText: "Sent" }).first()).toContainText(
    "已完成",
  );
});