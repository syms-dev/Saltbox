import { expect, sidewaysOverflow, test } from './fixtures';

const PAGES = [
  '/',
  '/apps',
  '/apps/discover',
  '/apps/saltbox/sonarr',
  '/apps/saltbox/sonarr?tab=logs',
  '/apps/saltbox/sonarr?tab=settings',
  '/activity',
  '/system',
  '/connect',
  '/config/accounts',
  '/config/inventory',
];

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
  const nav = page.getByRole('navigation', { name: 'Main' });
  await nav.getByRole('link', { name: /^Apps/ }).tap();
  await expect(page.getByRole('heading', { level: 1, name: 'Apps' })).toBeVisible();
  const [color, background] = await nav.getByRole('link', { name: /^Apps/ }).evaluate((el) => {
    const style = getComputedStyle(el);
    return [style.color, style.backgroundColor];
  });
  expect(color).not.toBe(background);
});

test('search opens from the top bar', async ({ page }) => {
  await page.goto('/');
  await page
    .getByRole('button', { name: /Search/ })
    .first()
    .tap();
  await expect(page.getByRole('dialog', { name: 'Search and commands' })).toBeVisible();
});
