import { type Locator, type Page, expect, test as base } from '@playwright/test';

/**
 * Every test fails on a console error or an uncaught exception in the page. App icons are
 * fetched from the apps' own addresses, which do not exist on the test box: they get a 404,
 * the way an app without an icon answers.
 */
export const test = base.extend<{ pageErrors: string[] }>({
  pageErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      await page.route(/e2e\.example/, (route) => route.fulfill({ body: '', status: 404 }));
      page.on('console', (message) => {
        // Chrome logs every 4xx response; a refused save or a missing icon is expected.
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

/** The open confirmation dialog with this title. */
export function dialog(page: Page, title: string | RegExp): Locator {
  return page.getByRole('dialog', { name: title });
}

/** Confirm the dialog titled `title` with its main button, and return the dialog's text. */
export async function confirm(page: Page, title: string | RegExp, button: string | RegExp): Promise<string> {
  const box = dialog(page, title);
  await expect(box).toBeVisible();
  const text = (await box.textContent()) ?? '';
  await box.getByRole('button', { name: button }).click();
  await expect(box).toBeHidden();
  return text;
}

/** Wait on a job page until the job has finished, and say how it ended. */
export async function jobOutcome(page: Page): Promise<'cancelled' | 'failed' | 'succeeded'> {
  await expect(page).toHaveURL(/\/activity\/[\w-]+$/);
  const done = page.getByText('Finished without errors.');
  const failed = page.getByText(/^The job failed/);
  const stopped = page.getByRole('main').getByText('Stopped', { exact: true });
  await expect(done.or(failed).or(stopped).first()).toBeVisible({ timeout: 20_000 });
  if (await done.isVisible()) return 'succeeded';
  if (await failed.isVisible()) return 'failed';
  return 'cancelled';
}
