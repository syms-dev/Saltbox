import { E2E_TOKEN } from '../playwright.config';
import { confirm, dialog, expect, jobOutcome, test } from './fixtures';

test.describe('daemon access', () => {
  // Node's fetch, not Playwright's request context, which carries the configured token.
  test('refuses API calls and job starts without the right token', async ({ baseURL }) => {
    const call = async (path: string, init: RequestInit = {}): Promise<number> =>
      (await fetch(`${baseURL ?? ''}${path}`, init)).status;
    expect(await call('/api/meta')).toBe(401);
    expect(await call('/api/openapi.json')).toBe(401);
    expect(await call('/api/state/facts?secrets=true')).toBe(401);
    expect(await call('/api/containers/sonarr/logs')).toBe(401);
    const start = { body: JSON.stringify({ kind: 'install', tags: ['sonarr'] }), method: 'POST' };
    expect(await call('/api/jobs', start)).toBe(401);
    expect(await call('/api/containers/sonarr/stop', { method: 'POST' })).toBe(401);
    expect(await call('/api/meta', { headers: { Authorization: `Bearer ${E2E_TOKEN}x` } })).toBe(401);
    expect(await call('/api/meta', { headers: { Authorization: `Bearer ${E2E_TOKEN}` } })).toBe(200);
  });

  test('refuses actions from a sibling site even with the token', async ({ baseURL }) => {
    const headers = { Authorization: `Bearer ${E2E_TOKEN}`, 'Sec-Fetch-Site': 'same-site' };
    for (const path of ['/api/saltbox/update', '/api/containers/sonarr/restart']) {
      expect((await fetch(`${baseURL ?? ''}${path}`, { headers, method: 'POST' })).status).toBe(403);
    }
  });
});

test.describe('home', () => {
  test('says what needs attention and launches apps', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toContainText(/need.* your attention/);
    const attention = page.getByRole('region', { name: 'Needs attention' });
    await expect(attention).toContainText('Prowlarr is unhealthy');
    await expect(attention).toContainText('Dozzle is not running');
    // The first visit starts the update check; the page refreshes when it lands.
    await expect(attention).toContainText('2 app updates available', { timeout: 20_000 });
    await expect(attention).toContainText('Saltbox update available');
    const sonarr = page.getByRole('link', { name: 'Open Sonarr (sonarr.e2e.example)' });
    await expect(sonarr).toHaveAttribute('href', 'https://sonarr.e2e.example');
    await expect(sonarr).toHaveAttribute('target', '_blank');
    await expect(page.getByRole('region', { name: 'Updates' })).toContainText('2 apps: Gluetun, Sonarr');
  });

  test('shows the VPN, downloads, what is playing and what is coming up', async ({ page }) => {
    await page.goto('/');
    const media = page.getByRole('region', { name: 'Media' });
    await expect(media.getByRole('region', { name: 'VPN' })).toContainText('Protected');
    await expect(media.getByRole('region', { name: 'VPN' })).toContainText('185.98.171.144');
    await expect(media.getByRole('region', { name: 'VPN' })).toContainText('51413');
    await expect(media.getByRole('region', { name: 'Downloads' })).toContainText('12.0 MiB/s');
    await expect(media.getByRole('region', { name: 'Downloads' })).toContainText('Some.Show.S03E04.1080p.WEB');
    await expect(media.getByRole('region', { name: 'Now playing' })).toContainText('Some Show');
    await expect(media.getByRole('region', { name: 'Now playing' })).toContainText('seed on Living Room TV');
    await expect(media.getByRole('region', { name: 'Coming up' })).toContainText('A Film');
  });

  test('fixes an unhealthy app and a stopped one from the attention list', async ({ page }) => {
    await page.goto('/');
    const attention = page.getByRole('region', { name: 'Needs attention' });
    await attention
      .getByRole('listitem')
      .filter({ hasText: 'Prowlarr is unhealthy' })
      .getByRole('button', { name: 'Restart' })
      .click();
    expect(await confirm(page, 'Restart prowlarr?', 'Restart prowlarr')).toContain('unavailable for a few seconds');
    await expect(page.getByRole('status').getByText('prowlarr restarted')).toBeVisible();
    await expect(attention).not.toContainText('Prowlarr is unhealthy');
    await attention
      .getByRole('listitem')
      .filter({ hasText: 'Dozzle is not running' })
      .getByRole('button', { name: 'Start' })
      .click();
    await expect(page.getByRole('status').getByText('dozzle started')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toContainText(/need.* your attention|Everything is running/);
    await expect(page.getByText('Dozzle is not running')).toHaveCount(0);
  });

  test('pinned apps stay first, across reloads', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Pin Sonarr' }).click();
    await expect(page.getByRole('button', { name: 'Unpin Sonarr' })).toHaveAttribute('aria-pressed', 'true');
    await page.reload();
    const tiles = page.getByRole('region', { name: 'Your apps' }).getByRole('listitem');
    await expect(tiles.first()).toContainText('Sonarr');
    await page.getByRole('button', { name: 'Unpin Sonarr' }).click();
  });
});

test.describe('navigation and search', () => {
  test('every menu entry opens its page; old links and unknown pages are handled', async ({ page }) => {
    await page.goto('/');
    for (const [name, heading] of [
      ['Apps', 'Apps'],
      ['Activity', 'Activity'],
      ['System', 'System'],
      ['Connect apps', 'Connect apps'],
      ['Config', 'Config'],
      ['Home', /attention|Everything/],
    ] as const) {
      await page
        .getByRole('navigation', { name: 'Main' })
        .getByRole('link', { name: new RegExp(`^${name}`) })
        .click();
      await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible();
    }
    await page.goto('/apps/saltbox/sonarr');
    await expect(page.getByRole('heading', { level: 1, name: 'Sonarr' })).toBeVisible();
    await page.goto('/jobs');
    await expect(page).toHaveURL(/\/activity$/);
    await page.goto('/no/such/page');
    await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
  });

  test('the command palette finds apps and pages from the keyboard', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.keyboard.press('Control+k');
    const palette = page.getByRole('dialog', { name: 'Search and commands' });
    await expect(palette).toBeVisible();
    await page.keyboard.type('radarr');
    await expect(palette.getByRole('option').first()).toContainText('Radarr');
    await page.keyboard.press('Enter');
    await expect(page.getByRole('heading', { level: 1, name: 'Radarr' })).toBeVisible();
    await page.keyboard.press('/');
    await page.keyboard.type('system');
    await page.keyboard.press('Enter');
    await expect(page.getByRole('heading', { level: 1, name: 'System' })).toBeVisible();
    await page.keyboard.press('Control+k');
    await page.keyboard.press('Escape');
    await expect(palette).toBeHidden();
  });
});

test.describe('apps', () => {
  test('lists installed apps with links, health and updates, and filters them', async ({ page }) => {
    await page.goto('/apps');
    const list = page.getByRole('list', { name: 'Installed apps' });
    const sonarr = list.getByRole('listitem').filter({ hasText: 'Sonarr' });
    await expect(sonarr.getByRole('link', { name: 'Open Sonarr' })).toHaveAttribute(
      'href',
      'https://sonarr.e2e.example',
    );
    await expect(sonarr.getByRole('button', { name: 'Update' })).toBeVisible({ timeout: 20_000 });
    await expect(list.getByRole('listitem').filter({ hasText: 'Radarr' })).toContainText('Up to date');
    await page.getByRole('button', { name: /^Updates/ }).click();
    await expect(list.getByRole('listitem')).toHaveCount(2);
    await page.getByRole('button', { name: /^All/ }).click();
    await page.getByLabel('Filter installed apps').fill('plex');
    await expect(list.getByRole('listitem')).toHaveCount(1);
  });

  test('cancelling the confirmation starts nothing', async ({ page }) => {
    await page.goto('/apps');
    const before = ((await (await page.request.get('/api/jobs')).json()) as { jobs: unknown[] }).jobs.length;
    const sonarr = page
      .getByRole('list', { name: 'Installed apps' })
      .getByRole('listitem')
      .filter({ hasText: 'Sonarr' });
    await sonarr.getByRole('button', { name: 'Update' }).click({ timeout: 20_000 });
    await dialog(page, 'Update Sonarr?').getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog(page, 'Update Sonarr?')).toBeHidden();
    await expect(page).toHaveURL(/\/apps$/);
    const after = ((await (await page.request.get('/api/jobs')).json()) as { jobs: unknown[] }).jobs.length;
    expect(after).toBe(before);
  });

  test('updating one app runs its tag and shows the outcome', async ({ page }) => {
    await page.goto('/apps');
    const sonarr = page
      .getByRole('list', { name: 'Installed apps' })
      .getByRole('listitem')
      .filter({ hasText: 'Sonarr' });
    await sonarr.getByRole('button', { name: 'Update' }).click({ timeout: 20_000 });
    await confirm(page, 'Update Sonarr?', 'Update Sonarr');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('sb install sonarr');
    expect(await jobOutcome(page)).toBe('succeeded');
    await expect(page.getByText(/12 tasks ok, 1 changed/)).toBeVisible();
  });

  test('updating Gluetun says it rebuilds what runs inside it, and does', async ({ page }) => {
    await page.goto('/apps/saltbox/gluetun');
    await page.getByRole('button', { name: 'Update' }).click({ timeout: 20_000 });
    expect(await confirm(page, 'Update Gluetun?', 'Update Gluetun')).toContain('qBittorrent');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('sb install gluetun,qbittorrent');
    expect(await jobOutcome(page)).toBe('succeeded');
  });

  test('installs an app from the catalog', async ({ page }) => {
    await page.goto('/apps/discover');
    await page.getByLabel('Search the catalog').fill('jellyfin');
    const entry = page
      .getByRole('list', { name: 'Catalog' })
      .getByRole('listitem')
      .filter({ has: page.getByRole('link', { exact: true, name: 'Jellyfin' }) });
    await entry.getByRole('button', { name: 'Install' }).click();
    expect(await confirm(page, 'Install Jellyfin?', 'Install Jellyfin')).toContain('sb install jellyfin');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('sb install jellyfin');
    expect(await jobOutcome(page)).toBe('succeeded');
  });

  test('an app page reads logs, stops and starts the container, and edits overrides', async ({ page }) => {
    await page.goto('/apps/saltbox/radarr');
    await page.getByRole('tab', { name: 'Logs' }).click();
    const log = page.getByRole('log', { name: 'radarr log' });
    await expect(log).toContainText('e2e log line 40');
    await page.getByLabel('Filter log lines').fill('WARN');
    await expect(log.getByText(/WARN/)).toHaveCount(3);

    await page.getByRole('tab', { name: 'Overview' }).click();
    await page.getByRole('button', { name: 'Stop' }).click();
    await confirm(page, 'Stop radarr?', 'Stop radarr');
    await expect(page.getByRole('status').getByText('radarr stopped')).toBeVisible();
    await expect(page.getByRole('row', { name: /radarr/ })).toContainText('Stopped');
    await page
      .getByRole('row', { name: /radarr/ })
      .getByRole('button', { name: 'Start' })
      .click();
    await expect(page.getByRole('row', { name: /radarr/ })).toContainText('Running');

    await page.getByRole('tab', { name: 'Settings' }).click();
    await page.getByLabel('Override key').fill('radarr_role_e2e_setting');
    await page.getByLabel('Override value').fill('on');
    await page.getByRole('button', { name: 'Set' }).click();
    const row = page.getByRole('row', { name: /radarr_role_e2e_setting/ });
    await expect(row).toContainText('on');
    await row.getByRole('button', { name: 'Remove' }).click();
    await expect(row).toHaveCount(0);
  });
});

test.describe('activity', () => {
  test('a failing playbook says where it failed and offers a re-run', async ({ page }) => {
    await page.goto('/activity');
    await page.getByText('Run an sb command').click();
    await page.getByLabel('Tags', { exact: true }).fill('e2e-fail');
    await page.getByRole('button', { name: 'sb install' }).click();
    expect(await jobOutcome(page)).toBe('failed');
    await expect(page.getByRole('alert')).toContainText('e2e failure');
    await page.getByRole('button', { name: 'Show it in the log' }).click();
    await expect(page.getByRole('log', { name: 'Job log' })).toContainText('fatal: [localhost]: FAILED!');
    await expect(page.getByRole('button', { name: 'Run again' })).toBeEnabled();
    await page.goto('/activity');
    await page.getByRole('button', { name: /^Failed/ }).click();
    await expect(page.getByRole('list', { name: 'Jobs' }).getByRole('link').first()).toContainText('e2e-fail');
  });

  test('a running job shows everywhere, blocks a second one, and can be cancelled', async ({ page }) => {
    await page.goto('/activity');
    await page.getByText('Run an sb command').click();
    await page.getByLabel('Tags', { exact: true }).fill('e2e-slow');
    await page.getByRole('button', { name: 'sb install' }).click();
    await expect(page.getByRole('log', { name: 'Job log' })).toContainText('TASK [e2e-slow : wait]', {
      timeout: 10_000,
    });
    await expect(page.getByRole('link', { name: /Running sb install e2e-slow/ })).toBeVisible();
    const second = await page.request.post('/api/jobs', { data: { kind: 'install', tags: ['sonarr'] } });
    expect(second.status()).toBe(409);
    await page.getByRole('button', { name: 'Cancel' }).click();
    await confirm(page, 'Cancel this job?', 'Cancel the job');
    expect(await jobOutcome(page)).toBe('cancelled');
    await expect(page.getByRole('status').getByText(/sb install e2e-slow interrupted/)).toBeVisible();
  });

  test('Run sb update on the System page starts sb update', async ({ page }) => {
    await page.goto('/system');
    await expect(page.getByText(/saltbox: master at \w{7} → \w{7}/)).toBeVisible({ timeout: 20_000 });
    await page.getByRole('button', { name: 'Run sb update' }).click();
    expect(await confirm(page, 'Update Saltbox?', 'Run sb update')).toContain('sb update');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('sb update');
    expect(await jobOutcome(page)).toBe('succeeded');
  });
});

test.describe('system and setup', () => {
  test('shows storage, mounts and services', async ({ page }) => {
    await page.goto('/system');
    await expect(page.getByRole('region', { name: 'Storage' }).getByRole('meter').first()).toBeVisible();
    await expect(page.getByRole('region', { name: 'Mounts' })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Saltbox services' })).toBeVisible();
  });

  test('shows resource use, Tailscale and backups, and backs up on request', async ({ page }) => {
    await page.goto('/system');
    const busiest = page.getByRole('table', { name: 'Busiest containers' });
    await expect(busiest.getByRole('row').nth(1)).toContainText('plex');
    await expect(busiest.getByRole('row').nth(1)).toContainText('31.5%');
    const tailscale = page.getByRole('region', { name: 'Tailscale' });
    await expect(tailscale).toContainText('Connected');
    await expect(tailscale).toContainText('ssh seed@saltbox');
    const backups = page.getByRole('region', { name: 'Backups' });
    await expect(backups).toContainText('weekly');
    await backups.getByRole('button', { name: 'Back up now' }).click();
    expect(await confirm(page, 'Back up Saltbox now?', 'Back up now')).toContain('stops your apps');
    await expect(page.getByRole('status').getByText('Backup started')).toBeVisible();
    await page.getByRole('status').getByRole('link', { name: 'Watch the log' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('sb install backup');
    expect(await jobOutcome(page)).toBe('succeeded');
  });

  test('an app page shows what its container uses', async ({ page }) => {
    await page.goto('/apps/saltbox/plex');
    await expect(page.getByRole('row', { name: /plex/ })).toContainText('31.5% CPU');
  });

  test('sets up Recyclarr profiles and syncs them', async ({ page }) => {
    await page.goto('/connect');
    const card = page.getByRole('region', { name: 'Quality profiles' });
    await expect(card.getByRole('checkbox', { name: /WEB-1080p/ })).toBeChecked();
    await expect(card.getByRole('button', { name: 'Sync now' })).toBeDisabled(); // nothing saved yet
    await card.getByRole('checkbox', { name: /UHD Bluray \+ WEB/ }).check();
    await card.getByRole('button', { name: 'Save profiles' }).click();
    await expect(page.getByRole('status').getByText('Profiles saved')).toBeVisible();
    await expect(card.getByRole('button', { name: 'Save profiles' })).toBeDisabled();
    await card.getByRole('button', { name: 'Preview changes' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('docker exec recyclarr recyclarr sync --preview');
    expect(await jobOutcome(page)).toBe('succeeded');
    await expect(page.getByRole('log', { name: 'Job log' })).toContainText('Created 42 New Custom Formats (preview)');
    await page.goto('/connect');
    await expect(page.getByRole('region', { name: 'Quality profiles' })).toContainText('Last run:');
    await expect(
      page.getByRole('region', { name: 'Quality profiles' }).getByRole('checkbox', { name: /UHD Bluray/ }),
    ).toBeChecked();
  });

  test('Connect apps lists every check per app without failing as a whole', async ({ page }) => {
    await page.goto('/connect');
    await expect(page.getByRole('region', { name: 'qBittorrent' })).toContainText('Login');
    await expect(page.getByRole('region', { name: 'Sonarr' })).toBeVisible();
    await page.getByRole('button', { name: 'Check again' }).click();
    await expect(page.getByRole('region', { name: 'Plex' })).toContainText('Movies library');
  });
});

test.describe('secrets', () => {
  const KEY = 'e2e-wireguard-private-key=';
  const PASSWORD = 'password12345678';

  test('config files hide secrets until asked, and saving keeps them', async ({ page }) => {
    await page.goto('/config/accounts');
    const editor = page.getByLabel('File contents');
    await expect(editor).toContainText('pass: \u2039hidden:user.pass\u203a');
    expect(await page.content()).not.toContain(PASSWORD);
    await expect(page.getByText(/hidden as/)).toBeVisible();

    await page.goto('/config/inventory');
    await expect(page.getByLabel('File contents')).toContainText(
      '\u2039hidden:gluetun_role_docker_envs_custom.WIREGUARD_PRIVATE_KEY\u203a',
    );
    expect(await page.content()).not.toContain(KEY);
    const text = await page.getByLabel('File contents').inputValue();
    await page.getByLabel('File contents').fill(text.replace('protonvpn', 'mullvad'));
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('unsaved changes')).toHaveCount(0);
    await page.getByRole('button', { name: 'Show secrets' }).click();
    await expect(page.getByLabel('File contents')).toContainText(KEY);
    await expect(page.getByLabel('File contents')).toContainText('mullvad');
    await page.getByRole('button', { name: 'Hide secrets' }).click();
    await expect(page.getByLabel('File contents')).not.toContainText(KEY);
  });

  test('app overrides hide secret values', async ({ page }) => {
    await page.goto('/apps/saltbox/gluetun?tab=settings');
    await expect(page.getByText('Passwords, tokens and keys are hidden.')).toBeVisible();
    expect(await page.content()).not.toContain(KEY);
    await page.getByRole('button', { name: 'Show secrets' }).click();
    const overrides = page.getByRole('region', { name: 'Your overrides' });
    await expect(overrides.getByRole('row', { name: /gluetun_role_docker_envs_custom/ })).toContainText(KEY);
  });

  test('an app without a config folder still counts as installed', async ({ page }) => {
    await page.goto('/apps');
    await expect(page.getByRole('list', { name: 'Installed apps' })).toContainText('Autoheal');
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
    await expect(page.getByText(/errors? across all files|No validation errors/)).toBeVisible();
  });

  test('saves the inventory with Ctrl+S and refuses invalid YAML', async ({ page }) => {
    await page.goto('/config/inventory');
    const editor = page.getByLabel('File contents');
    await editor.fill('---\nsonarr_role_e2e: "yes"\n');
    await editor.press('Control+s');
    await expect(page.getByText('No validation issues.')).toBeVisible();
    await expect(page.getByText('unsaved changes')).toHaveCount(0);
    await editor.fill('---\nbroken: [unclosed\n');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText(/Save failed/)).toBeVisible();
    await page.goto('/config/inventory');
    await expect(page.getByLabel('File contents')).toHaveValue('---\nsonarr_role_e2e: "yes"\n');
  });
});
