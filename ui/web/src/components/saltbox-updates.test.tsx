import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { RepoStatus } from '../api/types';
import { renderAt, stubApi } from '../test-utils';
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('repoLine', () => {
  it('shows the branch, the local commit and the newer remote one', () => {
    expect(repoLine(repo())).toBe('saltbox: claude/saltbox-gui-tui-bxul3c at 4153c10 → 9a8b7c6');
    expect(repoLine(repo({ branch: 'master', name: 'sandbox', status: 'current' }))).toBe('sandbox: master at 4153c10');
  });
});

describe('SaltboxUpdates', () => {
  it('runs sb update after confirming and opens the job', async () => {
    const api = stubApi({
      '/jobs': { busy: false, current: null, jobs: [], lock: null },
      'POST /saltbox/update': { id: 'job9', kind: 'update', status: 'running', tags: [] },
      '/updates': {
        checked_at: 1,
        error: '',
        images: {},
        repos: [
          repo(),
          repo({ detail: 'cannot read master', name: 'sandbox', path: '/opt/sandbox', status: 'unknown' }),
        ],
        running: false,
      },
    });
    renderAt(<SaltboxUpdates />);
    expect(await screen.findByText(/saltbox: claude\/saltbox-gui-tui-bxul3c at 4153c10 → 9a8b7c6/)).toBeInTheDocument();
    expect(screen.getByText('cannot read master')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Run sb update' }));
    const dialog = await screen.findByRole('dialog', { name: 'Update Saltbox?' });
    expect(dialog).toHaveTextContent('resets the Saltbox checkouts');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Run sb update' }));
    expect(await screen.findByText('job page')).toBeInTheDocument();
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith('/api/saltbox/update', expect.objectContaining({ method: 'POST' })),
    );
  });
});
