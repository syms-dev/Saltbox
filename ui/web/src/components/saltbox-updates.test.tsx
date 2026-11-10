import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { RepoStatus } from '../api/types';
import { SaltboxUpdates, repoLine } from './saltbox-updates';

function repo(overrides: Partial<RepoStatus> = {}): RepoStatus {
  return {
    branch: 'claude/saltbox-gui-tui-bxul3c',
    commit: '4153c10',
    detail: '',
    name: 'saltbox',
    path: '/srv/git/saltbox',
    remote_commit: '9a8b7c6',
    source: 'https://github.com/syms-dev/Saltbox.git',
    status: 'update',
    ...overrides,
  };
}

function respond(data: unknown): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('repoLine', () => {
  it('shows the branch, the local commit and the newer remote one', () => {
    expect(repoLine(repo())).toBe('saltbox: claude/saltbox-gui-tui-bxul3c at 4153c10 → 9a8b7c6');
    expect(repoLine(repo({ name: 'sandbox', branch: 'master', status: 'current' }))).toBe('sandbox: master at 4153c10');
  });
});

describe('SaltboxUpdates', () => {
  it('runs sb update after confirming and opens the job', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === '/api/updates') {
        return respond({
          checked_at: 1,
          error: '',
          images: {},
          repos: [
            repo(),
            repo({ name: 'sandbox', path: '/opt/sandbox', status: 'unknown', detail: 'cannot read master' }),
          ],
          running: false,
        });
      }
      if (url === '/api/jobs') return respond({ busy: false, current: null, jobs: [], lock: null });
      if (url === '/api/saltbox/update' && init?.method === 'POST') {
        return respond({ id: 'job9', kind: 'update', status: 'running', tags: [] });
      }
      return respond({});
    });
    vi.stubGlobal('fetch', fetchMock);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Routes>
            <Route element={<SaltboxUpdates />} path="/" />
            <Route element={<p>job page</p>} path="/jobs/:id" />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/saltbox: claude\/saltbox-gui-tui-bxul3c at 4153c10 → 9a8b7c6/)).toBeInTheDocument();
    expect(screen.getByText('cannot read master')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Run sb update' }));
    expect(confirm.mock.calls[0]?.[0]).toMatch(/resets saltbox to the latest commit/);
    expect(await screen.findByText('job page')).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/saltbox/update', expect.objectContaining({ method: 'POST' })),
    );
  });
});
