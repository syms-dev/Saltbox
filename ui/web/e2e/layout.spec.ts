import { expect, sidewaysOverflow, test } from './fixtures';

const PAGES = ['/', '/apps', '/apps/saltbox/sonarr', '/jobs', '/config/accounts', '/config/inventory'];

for (const path of PAGES) {
  test(`${path} fits the screen without scrolling sideways`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.waitForLoadState('networkidle');
    expect(await sidewaysOverflow(page)).toBe(0);
  });
}

test('the current menu entry stays readable after a tap', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { exact: true, name: 'Apps' }).tap();
  await expect(page.getByRole('heading', { level: 1, name: 'Apps' })).toBeVisible();
  const link = page.getByRole('link', { exact: true, name: 'Apps' });
  const [color, background] = await link.evaluate((el) => {
    const style = getComputedStyle(el);
    return [style.color, style.backgroundColor];
  });
  expect(color).not.toBe(background);
});
