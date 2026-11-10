import { type Page, expect, test as base } from '@playwright/test';

/** Every test fails on a console error or an uncaught exception in the page. */
export const test = base.extend<{ pageErrors: string[] }>({
  pageErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on('console', (message) => {
        // Chrome logs every 4xx response; a refused save is expected and shown in the page.
        const refused = /^Failed to load resource: the server responded with a status of 4\d\d/;
        if (message.type() === 'error' && !refused.test(message.text())) errors.push(message.text());
      });
      page.on('pageerror', (error) => errors.push(error.message));
      await use(errors);
      expect(errors, 'console errors').toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

/** How far the page scrolls sideways; 0 means nothing overflows the viewport. */
export async function sidewaysOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

/** Accept the next window.confirm and return its text. */
export function acceptNextConfirm(page: Page): Promise<string> {
  return new Promise((resolve) => {
    page.once('dialog', (dialog) => {
      resolve(dialog.message());
      void dialog.accept();
    });
  });
}

/** Wait for the job page to show a finished job and return its status label. */
export async function finishedStatus(page: Page): Promise<string> {
  await expect(page).toHaveURL(/\/jobs\/[\w-]+$/);
  const badge = page.getByText(/^(succeeded|failed|cancelled|interrupted)$/i).first();
  await expect(badge).toBeVisible({ timeout: 20_000 });
  return ((await badge.textContent()) ?? '').toLowerCase();
}
