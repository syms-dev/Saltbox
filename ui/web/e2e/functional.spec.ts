import { E2E_TOKEN } from '../playwright.config';
import { acceptNextConfirm, expect, finishedStatus, test } from './fixtures';

test.describe('daemon access', () => {
  // Node's fetch, not Playwright's request context, which carries the configured token.
  test('refuses API calls and job starts without the right token', async ({ baseURL }) => {
    const call = async (path: string, init: RequestInit = {}): Promise<number> =>
      (await fetch(`${baseURL ?? ''}${path}`, init)).status;
    expect(await call('/api/meta')).toBe(401);
    expect(await call('/api/openapi.json')).toBe(401);
    expect(await call('/api/state/facts?secrets=true')).toBe(401);
    const start = { body: JSON.stringify({ kind: 'install', tags: ['sonarr'] }), method: 'POST' };
    expect(await call('/api/jobs', start)).toBe(401);
    expect(await call('/api/meta', { headers: { Authorization: `Bearer ${E2E_TOKEN}x` } })).toBe(401);
    expect(await call('/api/meta', { headers: { Authorization: `Bearer ${E2E_TOKEN}` } })).toBe(200);
  });

  test('refuses job starts from a sibling site even with the token', async ({ baseURL }) => {
    const response = await fetch(`${baseURL ?? ''}/api/saltbox/update`, {
      headers: { Authorization: `Bearer ${E2E_TOKEN}`, 'Sec-Fetch-Site': 'same-site' },
      method: 'POST',
    });
    expect(response.status).toBe(403);
  });
});

test.describe('overview', () => {
  test('leads with what needs attention', async ({ page }) => {
    await page.goto('/');
    const attention = page.getByRole('region', { name: 'Needs attention' });
    // The first visit starts the update check; the overview polls until it lands.
    await expect(attention).toContainText('Saltbox update available (saltbox)', { timeout: 20_000 });
    await expect(attention.getByRole('link', { name: '2 app updates available: gluetun, sonarr' })).toBeVisible();
    await expect(attention).toContainText('prowlarr is unhealthy');
    await expect(attention).toContainText('dozzle is not running');
    await expect(page.getByText(/saltbox: master at \w{7} → \w{7}/)).toBeVisible();
    await expect(page.getByText(/of 7 managed containers running/)).toBeVisible();
  });

  test('every menu entry opens its page, deep links reload, unknown pages say so', async ({ page }) => {
    await page.goto('/');
    for (const [name, heading] of [
      ['Apps', 'Apps'],
      ['Jobs', 'Jobs'],
      ['Config', 'Config'],
      ['Overview', 'Overview'],
    ] as const) {
      await page.getByRole('link', { exact: true, name }).click();
      await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible();
    }
    await page.goto('/apps/saltbox/sonarr');
    await expect(page.getByRole('heading', { level: 1, name: 'Sonarr' })).toBeVisible();
    await page.goto('/no/such/page');
    await expect(page.getByText(/not found/i).first()).toBeVisible();
  });
});

test.describe('apps', () => {
  test('filters the catalog and lists installed apps with links, health and updates', async ({ page }) => {
    await page.goto('/apps');
    await page.getByLabel('Filter apps').fill('sonarr');
    await expect(page.locator('a.card', { hasText: 'Sonarr' }).first()).toBeVisible();
    await page.getByLabel('Filter apps').fill('');
    const installed = page.getByRole('region', { name: 'Installed' });
    const sonarr = installed.getByRole('row', { name: /Sonarr/ });
    await expect(sonarr.getByRole('link', { name: 'Open sonarr.e2e.example' })).toHaveAttribute(
      'href',
      'https://sonarr.e2e.example',
    );
    await expect(sonarr.getByRole('link', { name: 'Open sonarr.e2e.example' })).toHaveAttribute('target', '_blank');
    await expect(sonarr).toContainText('sonarr healthy');
    await expect(sonarr).toContainText('update available');
    await expect(installed.getByRole('row', { name: /Prowlarr/ })).toContainText('prowlarr unhealthy');
    await expect(installed.getByRole('row', { name: /Radarr/ })).toContainText('up to date');
    await expect(installed.getByRole('button', { name: 'Update all (2)' })).toBeVisible();
  });

  test('cancelling the confirmation starts nothing', async ({ page }) => {
    await page.goto('/apps');
    const before = (await (await page.request.get('/api/jobs')).json()) as { jobs: unknown[] };
    page.once('dialog', (dialog) => void dialog.dismiss());
    await page
      .getByRole('row', { name: /Sonarr/ })
      .getByRole('button', { name: 'Update' })
      .click();
    await expect(page).toHaveURL(/\/apps$/);
    const after = (await (await page.request.get('/api/jobs')).json()) as { jobs: unknown[] };
    expect(after.jobs.length).toBe(before.jobs.length);
  });

  test('updating one app runs its tag and streams the log', async ({ page }) => {
    await page.goto('/apps');
    const confirmed = acceptNextConfirm(page);
    await page
      .getByRole('row', { name: /Sonarr/ })
      .getByRole('button', { name: 'Update' })
      .click();
    expect(await confirmed).toContain('Update Sonarr?');
    await expect(page).toHaveURL(/\/jobs\/[\w-]+$/);
    await expect(page.getByRole('heading', { level: 1 })).toContainText('sb install sonarr');
    expect(await finishedStatus(page)).toBe('succeeded');
    await expect(page.getByText(/PLAY RECAP/)).toBeVisible();
  });

  test('updating Gluetun also rebuilds what runs inside it', async ({ page }) => {
    await page.goto('/apps');
    const confirmed = acceptNextConfirm(page);
    await page
      .getByRole('row', { name: /Gluetun/ })
      .getByRole('button', { name: 'Update' })
      .click();
    await confirmed;
    await expect(page.getByRole('heading', { level: 1 })).toContainText('sb install gluetun,qbittorrent');
    expect(await finishedStatus(page)).toBe('succeeded');
  });

  test('an app page shows health and edits inventory overrides', async ({ page }) => {
    await page.goto('/apps/saltbox/sonarr');
    await expect(page.getByText('sonarr healthy')).toBeVisible();
    await page.getByLabel('Override key').fill('sonarr_role_e2e_setting');
    await page.getByLabel('Override value').fill('on');
    await page.getByRole('button', { name: 'Set' }).click();
    const row = page.getByRole('row', { name: /sonarr_role_e2e_setting/ });
    await expect(row).toContainText('on');
    await row.getByRole('button', { name: 'Remove' }).click();
    await expect(row).toHaveCount(0);
  });
});

test.describe('jobs', () => {
  test('a failing playbook is reported as failed', async ({ page }) => {
    await page.goto('/jobs');
    await page.getByLabel('Tags', { exact: true }).fill('e2e-fail');
    await page.getByRole('button', { name: 'sb install' }).click();
    expect(await finishedStatus(page)).toBe('failed');
    await expect(page.getByRole('alert')).toContainText('The job failed');
    await expect(page.getByText(/fatal: \[localhost\]: FAILED!/)).toBeVisible();
    await expect(page.getByText(/exit code 2/)).toBeVisible();
  });

  test('a running job can be cancelled, and blocks a second one meanwhile', async ({ page }) => {
    await page.goto('/jobs');
    await page.getByLabel('Tags', { exact: true }).fill('e2e-slow');
    await page.getByRole('button', { name: 'sb install' }).click();
    await expect(page.getByText(/TASK \[e2e-slow : wait\]/)).toBeVisible({ timeout: 10_000 });
    const second = await page.request.post('/api/jobs', { data: { kind: 'install', tags: ['sonarr'] } });
    expect(second.status()).toBe(409);
    await page.getByRole('button', { name: 'Cancel' }).click();
    expect(await finishedStatus(page)).toMatch(/cancelled|interrupted|failed/);
    await page.getByRole('link', { name: '← Jobs' }).click();
    await expect(page.getByRole('row', { name: /e2e-slow/ }).first()).toBeVisible();
  });

  test('Run sb update on the overview starts sb update', async ({ page }) => {
    await page.goto('/');
    const confirmed = acceptNextConfirm(page);
    await page.getByRole('button', { name: 'Run sb update' }).click();
    expect(await confirmed).toContain('resets saltbox');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('sb update');
    expect(await finishedStatus(page)).toBe('succeeded');
  });
});

test.describe('config', () => {
  test('edits, reverts and validates config files', async ({ page }) => {
    await page.goto('/config');
    await expect(page).toHaveURL(/\/config\/accounts$/);
    const editor = page.getByLabel('File contents');
    await expect(editor).toContainText('user:');
    const original = await editor.inputValue();
    await editor.fill(`${original}\n# e2e edit\n`);
    await expect(page.getByText('unsaved changes')).toBeVisible();
    await page.getByRole('button', { name: 'Revert' }).click();
    await expect(editor).toHaveValue(original);
    await page.getByRole('button', { name: 'Validate all' }).click();
    await expect(page.getByText(/errors across all files/)).toBeVisible();
  });

  test('saves the inventory and refuses invalid YAML', async ({ page }) => {
    await page.goto('/config/inventory');
    const editor = page.getByLabel('File contents');
    await editor.fill('---\nsonarr_role_e2e: "yes"\n');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('No validation issues.')).toBeVisible();
    await editor.fill('---\nbroken: [unclosed\n');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText(/Save failed/)).toBeVisible();
    await page.reload();
    await expect(page.getByLabel('File contents')).toHaveValue('---\nsonarr_role_e2e: "yes"\n');
  });
});
