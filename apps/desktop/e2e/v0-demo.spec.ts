import { expect, test } from "@playwright/test";

const IMAP_PORT = "11430";

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
  await page.getByRole("button", { name: "同步" }).click();

  await expect(page.getByTestId("mail-sync-last-uid")).toHaveText(
    "last UID: 2",
    { timeout: 15_000 },
  );
  await expect(page.getByTestId("mail-sync-state")).toHaveText("IDLE");

  await expect(page.getByText("E2E One")).toBeVisible();
  await expect(page.getByText("E2E Two")).toBeVisible();
});