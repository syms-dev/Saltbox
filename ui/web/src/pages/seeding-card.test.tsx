import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { SeedingStatus } from '../api/types';
import { renderAt, stubApi } from '../test-utils';
import { SeedingCard, parseLimit, torrentCount } from './seeding-card';

const GIB = 1024 ** 3;

function status(overrides: Partial<SeedingStatus> = {}): SeedingStatus {
  return {
    categories: [
      { name: 'sonarr', seeding: 120, stopped: 2 },
      { name: '', seeding: 23, stopped: 10 },
    ],
    error: '',
    installed: true,
    limits: { action: 'stop', days: null, inactive_days: null, ratio: null },
    longest_seeding_days: 212.5,
    seeding: { count: 143, size: 212 * GIB },
    stopped: { count: 12, size: 30 * GIB },
    tools: [
      { installed: false, repo: 'sandbox', role: 'tqm', title: 'tqm' },
      { installed: true, repo: 'sandbox', role: 'qbit_manage', title: 'qBit Manage' },
    ],
    unlimited: true,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('helpers', () => {
  it('reads a limit as a positive number or nothing', () => {
    expect(parseLimit('2')).toBe(2);
    expect(parseLimit(' 1,5 ')).toBe(1.5);
    expect(parseLimit('')).toBeNull();
    expect(parseLimit('0')).toBeNull();
    expect(parseLimit('lots')).toBeNull();
  });

  it('counts torrents with their size', () => {
    expect(torrentCount({ count: 1, size: 2 * GIB })).toBe('1 torrent (2.0 GiB)');
    expect(torrentCount({ count: 0, size: 0 })).toBe('0 torrents');
  });
});

describe('SeedingCard', () => {
  it('says nothing will ever stop, and saves the limits typed in', async () => {
    const api = stubApi({
      '/seeding': status(),
      'PUT /seeding': status({
        limits: { action: 'stop', days: 14, inactive_days: null, ratio: 2 },
        unlimited: false,
      }),
    });
    renderAt(<SeedingCard />);
    const card = await screen.findByRole('region', { name: 'Seeding' });
    expect(card).toHaveTextContent('143 torrents (212.0 GiB), the longest for 212.5 days');
    expect(card).toHaveTextContent('12 torrents (30.0 GiB)');
    expect(card).toHaveTextContent('sonarr 122 · none 33');
    expect(card).toHaveTextContent('No seeding limit is set');
    expect(screen.getByRole('link', { name: 'qBit Manage' })).toHaveAttribute('href', '/apps/sandbox/qbit_manage');

    const saveButton = screen.getByRole('button', { name: 'Save limits' });
    expect(saveButton).toBeDisabled(); // nothing chosen yet, and no number is suggested for you
    fireEvent.click(screen.getByRole('checkbox', { name: /share ratio/ }));
    expect(saveButton).toBeDisabled();
    expect(card).toHaveTextContent('Enter a number above 0');
    fireEvent.change(screen.getByRole('textbox', { name: 'Share ratio' }), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('checkbox', { name: /after seeding/ }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Days of seeding' }), { target: { value: '14' } });
    fireEvent.click(saveButton);
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        '/api/seeding',
        expect.objectContaining({ body: JSON.stringify({ days: 14, ratio: 2 }), method: 'PUT' }),
      ),
    );
    await waitFor(() => expect(card).not.toHaveTextContent('No seeding limit is set'));
    expect(screen.getByRole('textbox', { name: 'Share ratio' })).toHaveValue('2');
    expect(screen.getByRole('button', { name: 'Save limits' })).toBeDisabled(); // saved: nothing to change
  });

  it('warns when qBittorrent removes torrents itself, and offers to change that', async () => {
    stubApi({
      '/seeding': status({
        limits: { action: 'remove', days: 7, inactive_days: 3, ratio: null },
        unlimited: false,
      }),
    });
    renderAt(<SeedingCard />);
    const card = await screen.findByRole('region', { name: 'Seeding' });
    expect(card).toHaveTextContent('set to remove torrents itself');
    expect(card).toHaveTextContent('idle for 3 days');
    expect(screen.getByRole('button', { name: 'Save limits' })).toBeEnabled();
  });

  it('shows why there are no numbers when qBittorrent did not answer, and stays away without it', async () => {
    stubApi({ '/seeding': { error: 'qbittorrent: the accounts.yml login was refused', installed: true, tools: [] } });
    renderAt(<SeedingCard />);
    expect(await screen.findByRole('region', { name: 'Seeding' })).toHaveTextContent('login was refused');
    expect(screen.queryByRole('button', { name: 'Save limits' })).toBeNull();
  });
});
