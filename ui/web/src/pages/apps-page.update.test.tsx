import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { App } from '../api/types';
import { makeApp, renderAt, stubApi } from '../test-utils';
import { AppsPage } from './apps-page';

function installed(role: string, update: 'current' | 'update'): App {
  return makeApp({
    containers: [
      { health: 'healthy', image: `img/${role}`, name: role, status: 'running', update, update_detail: '', urls: [] },
    ],
    installed: true,
    role,
    sb_tag: role,
    title: role.charAt(0).toUpperCase() + role.slice(1),
    update_available: update === 'update',
    urls: [`https://${role}.example.com`],
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('installed apps', () => {
  it('lists apps with their state and updates one after a confirmation', async () => {
    const api = stubApi({
      '/apps': [installed('sonarr', 'update'), installed('radarr', 'current')],
      '/jobs': { busy: false, current: null, jobs: [], lock: null },
      'POST /apps/saltbox/sonarr/update': { id: 'job1', kind: 'install', status: 'running', tags: ['sonarr'] },
      '/updates': { checked_at: 1, error: '', images: {}, running: false },
    });
    renderAt(<AppsPage tab="installed" />, '/apps');
    const list = await screen.findByRole('list', { name: 'Installed apps' });
    expect(within(list).getAllByText('Running')).toHaveLength(2);
    expect(within(list).getByText('Up to date')).toBeInTheDocument();
    expect(within(list).getByRole('link', { name: 'Open Sonarr' })).toHaveAttribute(
      'href',
      'https://sonarr.example.com',
    );
    expect(screen.getByRole('button', { name: 'Update all (1)' })).toBeInTheDocument();

    fireEvent.click(within(list).getByRole('button', { name: /Update/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Update Sonarr?' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Update Sonarr' }));
    expect(await screen.findByText('job page')).toBeInTheDocument();
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith('/api/apps/saltbox/sonarr/update', expect.objectContaining({ method: 'POST' })),
    );
  });

  it('cancelling the dialog starts nothing', async () => {
    const api = stubApi({
      '/apps': [installed('sonarr', 'update')],
      '/jobs': { busy: false, current: null, jobs: [], lock: null },
      '/updates': { checked_at: 1, error: '', images: {}, running: false },
    });
    renderAt(<AppsPage tab="installed" />, '/apps');
    const list = await screen.findByRole('list', { name: 'Installed apps' });
    fireEvent.click(within(list).getByRole('button', { name: /Update/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Update Sonarr?' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(api.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === 'POST')).toBe(false);
  });

  it('filters to apps with updates from the chip', async () => {
    stubApi({
      '/apps': [installed('sonarr', 'update'), installed('radarr', 'current')],
      '/jobs': { busy: false, current: null, jobs: [], lock: null },
      '/updates': { checked_at: 1, error: '', images: {}, running: false },
    });
    renderAt(<AppsPage tab="installed" />, '/apps');
    fireEvent.click(await screen.findByRole('button', { name: /Updates/ }));
    const list = screen.getByRole('list', { name: 'Installed apps' });
    expect(within(list).queryByText('Radarr')).not.toBeInTheDocument();
    expect(within(list).getByText('Sonarr')).toBeInTheDocument();
  });
});

describe('discover', () => {
  it('installs an app from the catalog after a confirmation', async () => {
    const api = stubApi({
      '/apps': [makeApp({ categories: ['Content Acquisition Apps > Collection Manager'] })],
      '/jobs': { busy: false, current: null, jobs: [], lock: null },
      'POST /jobs': { id: 'job2', kind: 'install', status: 'running', tags: ['sonarr'] },
    });
    renderAt(<AppsPage tab="discover" />, '/apps/discover');
    fireEvent.click(await screen.findByRole('button', { name: /Install/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Install Sonarr?' });
    expect(dialog).toHaveTextContent('sb install sonarr');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Install Sonarr' }));
    expect(await screen.findByText('job page')).toBeInTheDocument();
    const call = api.mock.calls.find(([url, init]) => url === '/api/jobs' && (init as RequestInit).method === 'POST');
    expect(JSON.parse((call?.[1] as RequestInit).body as string)).toEqual({ kind: 'install', tags: ['sonarr'] });
  });
});
