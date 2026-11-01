import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Overview } from '../api/types';
import { OverviewPage } from './overview-page';

const GIB = 1024 ** 3;

function overview(overrides: Partial<Overview> = {}): Overview {
  return {
    config_issues: {},
    containers: { available: true, running: 3, stopped: [], total: 3, unhealthy: [] },
    host: {
      disks: [{ free: 50 * GIB, path: '/', percent: 50, total: 100 * GIB, used: 50 * GIB }],
      mounts: [],
      reboot_required: false,
      units: [],
    },
    install: { configs_present: true, installed: true, roles_with_facts: ['sonarr'] },
    jobs: { busy: false, current: null, lock: null, recent: [] },
    services: [],
    ...overrides,
  };
}

function renderPage(data: Overview): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('OverviewPage', () => {
  it('says nothing needs attention on a healthy server', async () => {
    renderPage(overview());
    expect(await screen.findByRole('heading', { name: 'Needs attention' })).toBeInTheDocument();
    expect(screen.getByText(/Nothing\./)).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('lists config errors, stopped containers, full disks and pending reboots', async () => {
    renderPage(
      overview({
        config_issues: { accounts: [{ level: 'error', message: 'bad', path: 'user.email' }] },
        containers: { available: true, running: 2, stopped: ['plex'], total: 3, unhealthy: ['sonarr'] },
        host: {
          disks: [{ free: 2 * GIB, path: '/', percent: 98, total: 100 * GIB, used: 98 * GIB }],
          mounts: [],
          reboot_required: true,
          units: [],
        },
      }),
    );
    expect(await screen.findByRole('link', { name: 'accounts: 1 validation error' })).toHaveAttribute(
      'href',
      '/config/accounts',
    );
    expect(screen.getByText('sonarr is unhealthy')).toBeInTheDocument();
    expect(screen.getByText('plex is not running')).toBeInTheDocument();
    expect(screen.getByText(/\/ is 98% full/)).toBeInTheDocument();
    expect(screen.getByText('A reboot is pending')).toBeInTheDocument();
  });

  it('points at a failed last job', async () => {
    renderPage(
      overview({
        jobs: {
          busy: false,
          current: null,
          lock: null,
          recent: [
            {
              command: ['sb', 'install', 'sonarr'],
              command_line: 'sb install sonarr',
              finished_at: '2026-11-01T10:00:00+00:00',
              id: 'abc',
              kind: 'install',
              log_path: null,
              returncode: 2,
              started_at: '2026-11-01T09:00:00+00:00',
              status: 'failed',
              tags: ['sonarr'],
            },
          ],
        },
      }),
    );
    expect(await screen.findByRole('link', { name: 'The last job (install sonarr) failed' })).toHaveAttribute(
      'href',
      '/jobs/abc',
    );
  });
});
