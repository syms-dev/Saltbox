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
    await expect(attention).toContainText('4 app updates available', { timeout: 20_000 });
    await expect(attention).toContainText('Saltbox update available');
    const sonarr = page.getByRole('link', { name: 'Open Sonarr (sonarr.e2e.example)' });
    await expect(sonarr).toHaveAttribute('href', 'https://sonarr.e2e.example');
    await expect(sonarr).toHaveAttribute('target', '_blank');
    await expect(page.getByRole('region', { name: 'Updates' })).toContainText(
      '4 apps: Authelia, Gluetun, Sonarr, Traefik Proxy',
    );
  });

  test('says which updates want a reboot and restarts the server on request', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Saltbox UI 0.1.0')).toBeVisible();
    const reboot = page
      .getByRole('region', { name: 'Needs attention' })
      .getByRole('listitem')
      .filter({ hasText: 'A reboot is pending' });
    await expect(reboot).toContainText('Ubuntu updated libc6, linux-image-6.8.0-55-generic');
    await reboot.getByRole('button', { name: 'Restart the server' }).click();
    const question = dialog(page, 'Restart the server now?');
    await expect(question).toContainText('Everything on the server stops for a few minutes');
    await question.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByText('The server is restarting')).toHaveCount(0);
    await reboot.getByRole('button', { name: 'Restart the server' }).click();
    await confirm(page, 'Restart the server now?', 'Restart the server');
    await expect(page.getByRole('status').getByText('The server is restarting')).toBeVisible();
  });

  test('puts a failing drive first and shows every drive as Scrutiny sees it', async ({ page }) => {
    await page.goto('/');
    const first = page.getByRole('region', { name: 'Needs attention' }).getByRole('listitem').first();
    await expect(first).toContainText('Drive /dev/sdb is failing its health check', { timeout: 20_000 });
    await expect(first).toContainText('WDC WD80EFAX-68KNBN0 · 8.0 TB. Failing Scrutiny’s thresholds.');
    await first.getByRole('link', { name: 'Drive health' }).click();
    await expect(page).toHaveURL(/\/system#drives$/);
    const drives = page.getByRole('region', { name: 'Drive health' });
    await expect(drives).toBeInViewport();
    await expect(drives.getByRole('alert')).toContainText('1 of 3 drives is failing');
    const rows = drives.getByRole('listitem');
    await expect(rows).toHaveCount(3);
    await expect(rows.first()).toContainText('/dev/sdb');
    await expect(rows.first()).toContainText('Failing Scrutiny’s thresholds');
    const nvme = rows.filter({ hasText: '/dev/nvme0' });
    await expect(nvme).toContainText('NVMe');
    await expect(nvme).toContainText('Samsung SSD 980 PRO · 1.0 TB');
    await expect(nvme).toContainText('Healthy');
    await expect(nvme).toContainText('34 °C');
    await expect(nvme).toContainText('3.0 years');
    await expect(drives.getByRole('link', { name: 'Open Scrutiny' })).toHaveAttribute(
      'href',
      'https://scrutiny.e2e.example',
    );
  });

  test('explains a known error from the logs and lists the ones that keep repeating', async ({ page }) => {
    await page.goto('/');
    const known = page
      .getByRole('region', { name: 'Needs attention' })
      .getByRole('listitem')
      .filter({ hasText: "An indexer is behind Cloudflare's bot check" });
    await expect(known).toContainText('Prowlarr logged it once in the last day.', { timeout: 20_000 });
    await known.getByRole('link', { name: 'How to fix it' }).click();
    await expect(page).toHaveURL(/\/system#problems$/);
    const problems = page.getByRole('region', { name: 'Problems in app logs' });
    await expect(problems).toBeInViewport();
    await expect(problems).toContainText('Prowlarr · logged once');
    await expect(problems).toContainText('In Prowlarr, add that tag to the indexer.');
    await expect(problems).toContainText('Unable to access example.invalid, blocked by CloudFlare Protection.');
    await expect(problems.getByRole('link', { name: 'Open Prowlarr’s log' })).toHaveAttribute(
      'href',
      '/apps/saltbox/prowlarr?tab=logs',
    );
    await problems.getByText('1 other error that keeps repeating').click();
    await expect(problems).toContainText('Sonarr · 4 times');
    await expect(problems).toContainText('[Error] ImportService: Import failed for /downloads/Some.Show.S01E03');
    await problems.getByRole('button', { name: 'Check again' }).click();
    await expect(problems).toContainText('Prowlarr · logged once');
  });

  test('counts updates the same before and after the apps list arrives, and as the Apps page does', async ({
    page,
  }) => {
    // New images for Traefik and for the Redis the Authelia role runs are updates too. Home once
    // showed them by container name, then dropped them when the apps list loaded.
    let release = (): void => undefined;
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route('**/api/apps', async (route) => {
      await held;
      await route.continue();
    });
    await page.goto('/');
    const attention = page.getByRole('region', { name: 'Needs attention' });
    const updates = attention.getByRole('listitem').filter({ hasText: 'app updates available' });
    await expect(updates).toContainText('4 app updates available', { timeout: 20_000 });
    await expect(updates).toContainText('Authelia, Gluetun, Sonarr, Traefik Proxy');
    await expect(updates).not.toContainText('authelia-redis');
    const hero = page.locator('header').filter({ hasText: 'containers running' });
    await expect(hero).not.toContainText('apps installed'); // not "0 apps installed" while it loads
    release();
    await expect(hero).toContainText('12 apps installed');
    await expect(updates).toContainText('4 app updates available');
    await expect(updates).toContainText('Authelia, Gluetun, Sonarr, Traefik Proxy');

    await updates.getByRole('link', { name: 'Review' }).click();
    const list = page.getByRole('list', { name: 'Installed apps' });
    await expect(list.getByRole('listitem')).toHaveCount(4);
    const traefik = list.getByRole('listitem').filter({ hasText: 'Traefik Proxy' });
    await expect(traefik).toContainText('Core');
    await traefik.getByRole('button', { name: 'Update' }).click();
    const warning = dialog(page, 'Update Traefik Proxy?');
    await expect(warning).toContainText('Expect this page to drop for a moment');
    await warning.getByRole('button', { name: 'Cancel' }).click();
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
    await expect(list.getByRole('listitem')).toHaveCount(4);
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

  test('sb update shows its announcements and waits to be told about migrations', async ({ page }) => {
    await page.goto('/system');
    await expect(page.getByText(/saltbox: master at \w{7} → \w{7}/)).toBeVisible({ timeout: 20_000 });
    await page.getByRole('button', { name: 'Run sb update' }).click();
    expect(await confirm(page, 'Update Saltbox?', 'Run sb update')).toContain('waits for you');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('sb update --verbose --keep-branch');

    // sb stops at "Run all migration tags? (y/n)". The page asks instead, and nothing is typed for you.
    const question = page.getByRole('alert').filter({ hasText: 'waiting for your answer' });
    await expect(question).toBeVisible({ timeout: 20_000 });
    await expect(question.getByRole('row', { name: 'Saltbox e2e-migration 2031-01-01' })).toBeVisible();
    await expect(page.getByRole('link', { name: /sb update .* is waiting for your answer/ })).toBeVisible();
    const announcements = page.getByRole('region', { name: 'Announcements from this update' });
    await expect(announcements).toContainText('Test migration');
    await expect(announcements).toContainText('Something moved, and existing installs need a migration.');
    const log = page.getByRole('log', { name: 'Job log' });
    await expect(log).toContainText('1  Saltbox   e2e-migration   2031-01-01');
    await expect(log).not.toContainText('Validating Saltbox configuration');

    await question.getByRole('button', { name: 'Run the migrations' }).click();
    expect(await jobOutcome(page)).toBe('succeeded');
    await expect(question).toBeHidden();
    await expect(log).toContainText('Run all migration tags? (y/n): y');
    await expect(log).toContainText("Running migration 'e2e-migration' for Saltbox repository");
    await expect(log).toContainText('== Saltbox announcement, 2031-01-01: Test migration ==');
    await expect(announcements).toContainText('Test migration'); // kept with the finished job
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
    // Busiest first to begin with; any column sorts, and the rest of the containers are a click away.
    const use = page.getByRole('table', { name: 'Container resource use' });
    await expect(use.getByRole('row').nth(1)).toContainText('plex');
    await expect(use.getByRole('row').nth(1)).toContainText('31.5%');
    await expect(use.getByRole('row')).toHaveCount(9);
    await use.getByRole('button', { name: 'Container' }).click();
    await expect(use.getByRole('row').nth(1)).toContainText('authelia');
    await use.getByRole('button', { name: 'Memory' }).click();
    await expect(use.getByRole('row').nth(1)).toContainText('plex');
    await page.getByRole('button', { name: /^Show all \d+ containers$/ }).click();
    expect(await use.getByRole('row').count()).toBeGreaterThan(9);
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

  test('opens the web app over Tailscale and closes it again', async ({ page }) => {
    await page.goto('/system');
    const tailscale = page.getByRole('region', { name: 'Tailscale' });
    await tailscale.getByRole('button', { name: 'Turn on' }).click();
    expect(await confirm(page, 'Open the web app over Tailscale?', 'Turn on')).toContain('owner@example.com');
    await expect(tailscale.getByRole('link', { name: 'https://saltbox.tail-e2e.ts.net:8443/' })).toBeVisible();
    await tailscale.getByRole('button', { name: 'Turn off' }).click();
    await expect(tailscale.getByRole('button', { name: 'Turn on' })).toBeVisible();
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

  test('shows finished torrents that keep seeding and sets the limits that stop them', async ({ page }) => {
    await page.goto('/');
    const downloads = page.getByRole('region', { name: 'Media' }).getByRole('region', { name: 'Downloads' });
    const line = downloads.getByRole('link', { name: /seeding/ });
    await expect(line).toHaveText('3 seeding (16.0 GiB) · no limit set');
    await line.click();
    await expect(page).toHaveURL(/\/connect$/);
    const seeding = page.getByRole('region', { name: 'Seeding' });
    await expect(seeding).toContainText('3 torrents (16.0 GiB), the longest for 40 days');
    await expect(seeding).toContainText('Stopped, still in qBittorrent1 torrent (6.0 GiB)');
    await expect(seeding).toContainText('No seeding limit is set');
    const save = seeding.getByRole('button', { name: 'Save limits' });
    await expect(save).toBeDisabled();
    await seeding.getByRole('checkbox', { name: /share ratio/ }).check();
    await seeding.getByRole('textbox', { name: 'Share ratio' }).fill('2');
    await seeding.getByRole('checkbox', { name: /after seeding/ }).check();
    await seeding.getByRole('textbox', { name: 'Days of seeding' }).fill('14');
    await save.click();
    await expect(page.getByRole('status').getByText('Seeding limits saved')).toBeVisible();
    await expect(seeding).not.toContainText('No seeding limit is set');

    await page.reload();
    await expect(
      page.getByRole('region', { name: 'Seeding' }).getByRole('textbox', { name: 'Share ratio' }),
    ).toHaveValue('2');
    const saved = (await (await page.request.get('/api/seeding')).json()) as { limits: unknown; unlimited: boolean };
    expect(saved.limits).toEqual({ action: 'stop', days: 14, inactive_days: null, ratio: 2 });
    expect(saved.unlimited).toBe(false);
    // Leave the box as it was found.
    await page.request.put('/api/seeding', { data: { days: null, ratio: null } });
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

test.describe('automation', () => {
  test('saves alert settings, hides the URL and sends a test', async ({ page }) => {
    await page.goto('/automation');
    const alerts = page.getByRole('region', { exact: true, name: 'Alerts' });
    await alerts.getByLabel('Send alerts').check();
    await alerts.getByLabel('Send to (Apprise URL)').fill('ntfy://e2e-secret-topic');
    await alerts.getByLabel('A disk is over 90% full').uncheck();
    await alerts.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('status').getByText('Alert settings saved')).toBeVisible();
    await page.reload();
    await expect(page.getByRole('region', { exact: true, name: 'Alerts' })).toContainText('\u2039hidden\u203a');
    expect(await page.content()).not.toContain('e2e-secret-topic');
    await expect(
      page.getByRole('region', { exact: true, name: 'Alerts' }).getByLabel('A disk is over 90% full'),
    ).not.toBeChecked();
    await page
      .getByRole('region', { exact: true, name: 'Alerts' })
      .getByRole('button', { name: 'Send a test alert' })
      .click();
    await expect(page.getByRole('status').getByText('Test alert sent')).toBeVisible();
  });

  test('runs maintenance now, skipping excluded apps', async ({ page }) => {
    await page.goto('/automation');
    const maintenance = page.getByRole('region', { name: 'Nightly maintenance' });
    await maintenance.getByLabel('Run every night').check();
    await maintenance.getByLabel('Gluetun').check();
    await maintenance.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('status').getByText('Maintenance settings saved')).toBeVisible();
    await expect(maintenance).toContainText('Next run');
    await page.reload();
    await page.getByRole('region', { name: 'Nightly maintenance' }).getByRole('button', { name: 'Run now' }).click();
    await confirm(page, 'Run maintenance now?', 'Run maintenance');
    await expect(page.getByRole('status').getByText('Maintenance started')).toBeVisible();
    await expect(async () => {
      await page.reload();
      await expect(page.getByRole('region', { name: 'Nightly maintenance' })).toContainText('succeeded', {
        timeout: 1_000,
      });
    }).toPass({ timeout: 30_000 });
    const last = page.getByRole('region', { name: 'Nightly maintenance' });
    await expect(last.getByRole('link', { name: /update Authelia, Sonarr, Traefik Proxy/ })).toBeVisible();
    await expect(last).not.toContainText('update Gluetun');
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

test.describe('uninstall', () => {
  test('refuses what other things need, and removes an app with its settings when asked', async ({ page }) => {
    await page.goto('/apps/saltbox/traefik');
    await expect(page.getByRole('button', { name: 'Reinstall' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Uninstall' })).toHaveCount(0);

    await page.goto('/apps/saltbox/gluetun');
    await page.getByRole('button', { name: 'Uninstall' }).click();
    const refused = page.getByRole('status').filter({ hasText: 'Gluetun cannot be uninstalled yet' });
    await expect(refused).toContainText("qbittorrent runs inside gluetun's network");

    await page.goto('/apps/saltbox/lidarr');
    await page.getByRole('button', { name: 'Uninstall' }).click();
    const question = dialog(page, 'Uninstall Lidarr?');
    await expect(question).toContainText('Stops and removes the container lidarr');
    await expect(question).toContainText('installing it again later brings it back as it was');
    await question.getByRole('checkbox', { name: /Also delete its settings and database/ }).check();
    await expect(question).toContainText('Installing it again later starts from scratch.');
    await question.getByRole('button', { name: 'Uninstall Lidarr' }).click();
    await expect(page.getByRole('status').getByText('Lidarr uninstalled')).toBeVisible();
    await expect(page).toHaveURL(/\/apps$/);
    const list = page.getByRole('list', { name: 'Installed apps' });
    await expect(list.getByRole('listitem').filter({ hasText: 'Sonarr' })).toBeVisible();
    await expect(list.getByRole('listitem').filter({ hasText: 'Lidarr' })).toHaveCount(0);
    const plan = (await (await page.request.get('/api/apps/saltbox/lidarr/uninstall')).json()) as {
      containers: string[];
      folders: string[];
    };
    expect(plan.containers).toEqual([]);
    expect(plan.folders).toEqual([]);
  });
});
