import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { LogProblems } from '../api/types';
import { renderAt, stubApi } from '../test-utils';
import { ProblemsCard, findings, problemAttention } from './problems-card';

const PROBLEMS: LogProblems = {
  available: true,
  checked_at: Date.now() / 1000,
  containers: [
    {
      app: { repo: 'saltbox', role: 'autoscan', title: 'Autoscan' },
      groups: [
        {
          count: 48,
          last_seen: new Date().toISOString(),
          message: 'ERR Anchor files unavailable, retaining queued scans',
          rule: {
            fix: ['Create the file once: `touch /mnt/local/mounted.bin`.', 'Or remove the anchors entry.'],
            id: 'autoscan-anchor',
            meaning: 'Autoscan tells Plex about new files only while its anchor file exists.',
            severity: 'problem',
            title: 'Autoscan is holding back every scan',
          },
        },
      ],
      name: 'autoscan',
    },
    {
      app: { repo: 'saltbox', role: 'bazarr', title: 'Bazarr' },
      groups: [
        {
          count: 1,
          last_seen: '',
          message: "BAZARR Error ('.iso' is not a valid video extension)",
          rule: {
            fix: ['Replace the file.'],
            id: 'bazarr-not-a-video',
            meaning: 'Not a video it understands.',
            severity: 'notice',
            title: 'Bazarr cannot read a file in your library',
          },
        },
      ],
      name: 'bazarr',
    },
    {
      app: null,
      groups: [{ count: 5, last_seen: '', message: '[Error] Import failed for /downloads/x', rule: null }],
      name: 'mystery',
    },
  ],
  scanned: 25,
  window: '24h',
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('problemAttention', () => {
  it('raises only known errors that mean something is not working', () => {
    expect(findings(PROBLEMS)).toHaveLength(3);
    expect(problemAttention(undefined)).toEqual([]);
    expect(problemAttention(PROBLEMS)).toEqual([
      {
        actions: [{ kind: 'link', label: 'How to fix it', to: '/system#problems' }],
        detail: 'Autoscan logged it 48 times in the last day.',
        id: 'log:autoscan:autoscan-anchor',
        title: 'Autoscan is holding back every scan',
        tone: 'warn',
      },
    ]);
  });
});

describe('ProblemsCard', () => {
  it('explains the known errors, lists the rest, and reads the logs again on request', async () => {
    // The stub ignores query strings: the first read is the scan, the second the refresh.
    let reads = 0;
    const api = stubApi({ '/problems': () => (reads++ === 0 ? PROBLEMS : { ...PROBLEMS, containers: [] }) });
    renderAt(<ProblemsCard />);
    const card = await screen.findByRole('region', { name: 'Problems in app logs' });
    await waitFor(() => expect(card).toHaveTextContent('Autoscan is holding back every scan'));
    expect(card).toHaveTextContent('Autoscan · logged 48 times, last just now');
    expect(screen.getByText('touch /mnt/local/mounted.bin').tagName).toBe('CODE');
    expect(card).toHaveTextContent('Bazarr · logged once · harmless');
    expect(screen.getByRole('link', { name: 'Open Autoscan’s log' })).toHaveAttribute(
      'href',
      '/apps/saltbox/autoscan?tab=logs',
    );
    expect(card).toHaveTextContent('1 other error that keeps repeating');
    expect(card).toHaveTextContent('mystery · 5 times');

    fireEvent.click(screen.getByRole('button', { name: 'Check again' }));
    await waitFor(() => expect(card).toHaveTextContent('No error keeps coming back in the last day of 25 containers'));
    expect(api).toHaveBeenCalledWith('/api/problems?refresh=true', expect.anything());
  });
});
