import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { SelfStatus } from '../api/types';
import { renderAt, stubApi } from '../test-utils';
import { SelfUpdateCard, installedLine, newerLine, selfAttention } from './self-update';
import { isOutdated } from './shell';

function status(overrides: Partial<SelfStatus> = {}): SelfStatus {
  return {
    can_update: true,
    checked_at: 1,
    detail: '',
    latest: null,
    mode: 'source',
    source: { branch: 'main', commit: '1111111', path: '/srv/git/saltbox', remote_commit: '2222222' },
    update_available: true,
    version: '0.1.0',
    ...overrides,
  };
}

const WHEEL = status({
  latest: { url: 'https://example.invalid/x.whl', version: '0.2.0' },
  mode: 'wheel',
  source: null,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('what the card says', () => {
  it('describes each kind of install and what is newer', () => {
    expect(installedLine(status())).toBe('0.1.0, running from a source checkout at 1111111');
    expect(newerLine(status())).toBe('New commits are available (2222222).');
    expect(installedLine(WHEEL)).toBe('0.1.0, installed from a release');
    expect(newerLine(WHEEL)).toBe('Version 0.2.0 is available.');
    expect(newerLine(status({ update_available: false }))).toBe('Up to date.');
    const stuck = status({ can_update: false, detail: 'npm is not installed', update_available: false });
    expect(newerLine(stuck)).toBe('npm is not installed');
  });

  it('offers the update on Home only when there is one that can be applied', () => {
    expect(selfAttention(undefined)).toEqual([]);
    expect(selfAttention(status({ update_available: false }))).toEqual([]);
    expect(selfAttention(status({ can_update: false }))).toEqual([]);
    expect(selfAttention(WHEEL)).toEqual([
      {
        actions: [{ kind: 'selfUpdate', label: 'Update Saltbox UI' }],
        detail: 'Version 0.2.0 is available.',
        id: 'self-update',
        title: 'Saltbox UI update available',
        tone: 'info',
      },
    ]);
  });

  it('notices when the daemon serves a newer web app than this page', () => {
    expect(isOutdated(undefined)).toBe(false);
    expect(isOutdated('build-a')).toBe(false); // the first one seen is the one this page runs
    expect(isOutdated('build-a')).toBe(false);
    expect(isOutdated('build-b')).toBe(true);
  });
});

describe('SelfUpdateCard', () => {
  it('updates after confirming and opens the job', async () => {
    const api = stubApi({
      'POST /self/update': { command_line: 'python -m saltbox_ui.selfupdate', id: 'job7', kind: 'selfupdate' },
      '/jobs': { busy: false, current: null, jobs: [], lock: null },
      '/self': WHEEL,
    });
    renderAt(<SelfUpdateCard />);
    const card = await screen.findByRole('region', { name: 'Saltbox UI version' });
    await waitFor(() => expect(card).toHaveTextContent('0.1.0, installed from a release'));
    expect(card).toHaveTextContent('Version 0.2.0 is available.');
    fireEvent.click(within(card).getByRole('button', { name: 'Update Saltbox UI' }));
    const dialog = await screen.findByRole('dialog', { name: 'Update Saltbox UI?' });
    expect(dialog).toHaveTextContent('reloads by itself on the new version');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Update Saltbox UI' }));
    expect(await screen.findByText('job page')).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith('/api/self/update', expect.objectContaining({ method: 'POST' }));
  });

  it('has nothing to press when up to date, and looks again on request', async () => {
    let checks = 0;
    const api = stubApi({
      '/jobs': { busy: false, current: null, jobs: [], lock: null },
      '/self': () => (checks++ === 0 ? status({ update_available: false }) : status()),
    });
    renderAt(<SelfUpdateCard />);
    const card = await screen.findByRole('region', { name: 'Saltbox UI version' });
    await waitFor(() => expect(card).toHaveTextContent('Up to date.'));
    expect(within(card).getByRole('button', { name: 'Update Saltbox UI' })).toBeDisabled();
    fireEvent.click(within(card).getByRole('button', { name: 'Check now' }));
    await waitFor(() => expect(card).toHaveTextContent('New commits are available (2222222).'));
    expect(api).toHaveBeenCalledWith('/api/self?refresh=true', expect.anything());
    expect(within(card).getByRole('button', { name: 'Update Saltbox UI' })).toBeEnabled();
  });
});
