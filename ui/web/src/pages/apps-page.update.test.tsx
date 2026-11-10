import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { App } from '../api/types';
import { AppsPage } from './apps-page';

function app(role: string, update: 'current' | 'update'): App {
  return {
    app_links: [],
    categories: [],
    containers: [
      { health: 'healthy', image: `img/${role}`, name: role, status: 'running', update, update_detail: '', urls: [] },
    ],
    default_instances: [role],
    docs_url: '',
    install_tag: role,
    installed: true,
    instances: [role],
    link: '',
    main_tags: [],
    repo: 'saltbox',
    role,
    sb_tag: role,
    section: 'apps',
    selector: null,
    summary: '',
    supports_instances: true,
    tags: [role],
    title: role.charAt(0).toUpperCase() + role.slice(1),
    update_available: update === 'update',
    urls: [`https://${role}.thesyms.ca`],
    when: [],
  };
}

const JOB = {
  command: ['sb', 'install', 'sonarr'],
  command_line: 'sb install sonarr',
  finished_at: null,
  id: 'job1',
  kind: 'install',
  log_path: null,
  returncode: null,
  started_at: null,
  status: 'running',
  tags: ['sonarr'],
};

function respond(data: unknown): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('installed apps', () => {
  it('links to each app and updates the one that needs it', async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? 'GET'} ${url}`);
        if (url === '/api/apps') return respond([app('sonarr', 'update'), app('radarr', 'current')]);
        if (url === '/api/updates') {
          return respond({ checked_at: 1_800_000_000, error: '', images: {}, running: false });
        }
        if (url === '/api/apps/saltbox/sonarr/update') return respond(JOB);
        return respond({});
      }),
    );
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/apps']}>
          <Routes>
            <Route element={<AppsPage />} path="/apps" />
            <Route element={<p>job page</p>} path="/jobs/:id" />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole('link', { name: 'Open sonarr.thesyms.ca' })).toHaveAttribute(
      'href',
      'https://sonarr.thesyms.ca',
    );
    expect(screen.getByText('update available')).toBeInTheDocument();
    expect(screen.getByText('up to date')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Update all (1)' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Update' }));
    expect(confirm).toHaveBeenCalled();
    await waitFor(() => expect(screen.getByText('job page')).toBeInTheDocument());
    expect(calls).toContain('POST /api/apps/saltbox/sonarr/update');
  });

  it('does nothing when the update is not confirmed', async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? 'GET'} ${url}`);
        if (url === '/api/apps') return respond([app('sonarr', 'update')]);
        return respond({ checked_at: null, error: '', images: {}, running: false });
      }),
    );
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <AppsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole('button', { name: 'Update' }));
    expect(calls.some((c) => c.startsWith('POST'))).toBe(false);
  });
});
