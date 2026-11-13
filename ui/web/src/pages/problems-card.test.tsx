import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { LogGroup, LogProblems } from '../api/types';
import { renderAt, stubApi } from '../test-utils';
import { ProblemsCard, findings, problemAttention } from './problems-card';

const ANCHOR: LogGroup = {
  action: {
    detail: 'Creates an empty /mnt/local/mounted.bin, owned by whoever owns /mnt/local.',
    id: 'create-anchor',
    label: 'Create the anchor file',
  },
  count: 48,
  key: 'log:autoscan:autoscan-anchor',
  last_seen: new Date().toISOString(),
  message: 'ERR Anchor files unavailable, retaining queued scans',
  rule: {
    fix: ['Create it once: `touch /mnt/local/mounted.bin`.', 'Autoscan then sends what it held back.'],
    id: 'autoscan-anchor',
    meaning: 'Autoscan tells Plex about new files only while its anchor file exists.',
    severity: 'problem',
    title: 'Autoscan is holding back every scan',
  },
};

const ISO: LogGroup = {
  count: 42,
  key: 'log:bazarr:bazarr-not-a-video',
  last_seen: '',
  message: "BAZARR Error ('.iso' is not a valid video extension)",
  more_subjects: 3,
  rule: {
    fix: ['Replace each file listed here.'],
    id: 'bazarr-not-a-video',
    meaning: 'Not a video it understands.',
    severity: 'notice',
    title: 'Bazarr cannot read a file in your library',
  },
  subjects: ['/mnt/unionfs/Media/TV/A Show/Season 03/A Show - s03e09.iso'],
};

const UNKNOWN: LogGroup = {
  count: 5,
  key: 'log:mystery:0a1b2c3d4e5f',
  last_seen: '',
  message: '[Error] Import failed for /downloads/x',
  rule: null,
};

function problems(overrides: Partial<Record<'anchor' | 'iso' | 'unknown', Partial<LogGroup>>> = {}): LogProblems {
  return {
    available: true,
    checked_at: Date.now() / 1000,
    cloud_storage: false,
    containers: [
      {
        app: { repo: 'saltbox', role: 'autoscan', title: 'Autoscan' },
        groups: [{ ...ANCHOR, ...overrides.anchor }],
        name: 'autoscan',
      },
      {
        app: { repo: 'saltbox', role: 'bazarr', title: 'Bazarr' },
        groups: [{ ...ISO, ...overrides.iso }],
        name: 'bazarr',
      },
      { app: null, groups: [{ ...UNKNOWN, ...overrides.unknown }], name: 'mystery' },
    ],
    scanned: 25,
    window: '24h',
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('problemAttention', () => {
  it('raises only known errors that mean something is not working, until they are dismissed', () => {
    expect(findings(problems())).toHaveLength(3);
    expect(problemAttention(undefined)).toEqual([]);
    expect(problemAttention(problems())).toEqual([
      {
        actions: [{ kind: 'link', label: 'How to fix it', to: '/system#problems' }],
        detail: 'Autoscan logged it 48 times in the last day.',
        id: 'log:autoscan:autoscan-anchor',
        title: 'Autoscan is holding back every scan',
        tone: 'warn',
      },
    ]);
    expect(problemAttention(problems({ anchor: { dismissed: true } }))).toEqual([]);
  });
});

describe('ProblemsCard', () => {
  it('shows each issue as its own card, worst first, with what it is about', async () => {
    stubApi({ '/problems': problems() });
    renderAt(<ProblemsCard />);
    const card = await screen.findByRole('region', { name: 'Problems in app logs' });
    await waitFor(() => expect(within(card).getAllByRole('article')).toHaveLength(3));
    expect(card).toHaveTextContent('3 issues in the last day of 25 containers');
    const [anchor, unknown, iso] = within(card).getAllByRole('article');

    expect(anchor).toHaveAccessibleName('Autoscan is holding back every scan');
    expect(anchor).toHaveTextContent('Needs fixing');
    expect(anchor).toHaveTextContent('Autoscan · logged 48 times, last just now');
    expect(within(anchor as HTMLElement).getByText('touch /mnt/local/mounted.bin').tagName).toBe('CODE');
    expect(within(anchor as HTMLElement).getByRole('link', { name: /Open Autoscan’s log/ })).toHaveAttribute(
      'href',
      '/apps/saltbox/autoscan?tab=logs',
    );

    expect(unknown).toHaveAccessibleName('mystery keeps logging the same error');
    expect(unknown).toHaveTextContent('Unexplained');
    expect(unknown).toHaveTextContent('There is no explanation on file for this one.');
    expect(unknown).toHaveTextContent('[Error] Import failed for /downloads/x');

    expect(iso).toHaveTextContent('Harmless');
    expect(iso).toHaveTextContent('Bazarr · logged 42 times');
    expect(iso).toHaveTextContent('/mnt/unionfs/Media/TV/A Show/Season 03/A Show - s03e09.iso');
    expect(iso).toHaveTextContent('and 3 more');
  });

  it('applies the fix the daemon offers and shows the scan that follows', async () => {
    const api = stubApi({
      'POST /problems/fix': {
        created: ['/mnt/local/mounted.bin'],
        fixed: 'create-anchor',
        problems: { ...problems(), containers: [] },
      },
      '/problems': problems(),
    });
    renderAt(<ProblemsCard />);
    const anchor = await screen.findByRole('article', { name: 'Autoscan is holding back every scan' });
    expect(anchor).toHaveTextContent('Creates an empty /mnt/local/mounted.bin');
    // Only the finding with a fix on offer has the button.
    expect(screen.getAllByRole('button', { name: 'Create the anchor file' })).toHaveLength(1);
    fireEvent.click(within(anchor).getByRole('button', { name: 'Create the anchor file' }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        '/api/problems/fix',
        expect.objectContaining({ body: JSON.stringify({ key: 'log:autoscan:autoscan-anchor' }), method: 'POST' }),
      ),
    );
    expect(await screen.findByText('Created /mnt/local/mounted.bin.')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryAllByRole('article')).toHaveLength(0));
    expect(screen.getByRole('region', { name: 'Problems in app logs' })).toHaveTextContent(
      'No error keeps coming back in the last day of 25 containers',
    );
  });

  it('dismisses an issue, keeps it in a list of its own, and brings it back on request', async () => {
    let dismissed = false;
    const api = stubApi({
      'POST /dismissals': () => {
        dismissed = true;
        return { dismissed: true };
      },
      'POST /dismissals/restore': () => {
        dismissed = false;
        return { restored: true };
      },
      '/problems': () => problems({ iso: { dismissed } }),
    });
    renderAt(<ProblemsCard />);
    const iso = await screen.findByRole('article', { name: 'Bazarr cannot read a file in your library' });
    fireEvent.click(within(iso).getByRole('button', { name: 'Dismiss' }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        '/api/dismissals',
        expect.objectContaining({
          body: JSON.stringify({
            key: 'log:bazarr:bazarr-not-a-video',
            label: 'Bazarr cannot read a file in your library',
          }),
        }),
      ),
    );
    await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(2));
    const card = screen.getByRole('region', { name: 'Problems in app logs' });
    expect(card).toHaveTextContent('1 dismissed issue');
    fireEvent.click(within(card).getByRole('button', { name: 'Show again' }));
    await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(3));
    expect(card).not.toHaveTextContent('dismissed issue');
  });

  it('asks Claude only after saying what is sent, and shows the answer as Claude’s', async () => {
    const explanation = {
      asked_at: Date.now() / 1000,
      cause: 'The import path does not exist inside the container.',
      confidence: 'medium' as const,
      lines_sent: 25,
      steps: ['Check the remote path mapping in `Settings > Download Clients`.'],
      summary: 'It cannot move a finished download into the library.',
    };
    let asked = false;
    const api = stubApi({
      'POST /problems/explain': () => {
        asked = true;
        return explanation;
      },
      '/explain': { installed: true, method: 'claude.ai', signed_in: true, user: 'seed' },
      '/problems': () => problems({ unknown: { explanation: asked ? explanation : null } }),
    });
    renderAt(<ProblemsCard />);
    const unknown = await screen.findByRole('article', { name: 'mystery keeps logging the same error' });
    fireEvent.click(await within(unknown).findByRole('button', { name: 'Ask Claude' }));
    const dialog = await screen.findByRole('dialog', { name: 'Ask Claude about this mystery error?' });
    expect(dialog).toHaveTextContent('sends the error and about 25 lines of mystery’s log around it to Anthropic');
    expect(dialog).toHaveTextContent('signed in as seed');
    expect(dialog).toHaveTextContent('nothing it says is run');
    expect(asked).toBe(false); // nothing leaves the server before the person agrees
    fireEvent.click(within(dialog).getByRole('button', { name: 'Ask Claude' }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        '/api/problems/explain',
        expect.objectContaining({ body: JSON.stringify({ again: false, key: 'log:mystery:0a1b2c3d4e5f' }) }),
      ),
    );
    await waitFor(() => expect(unknown).toHaveTextContent('Claude’s explanation · reasonably sure'));
    expect(unknown).toHaveTextContent('It cannot move a finished download into the library.');
    expect(within(unknown).getByText('Settings > Download Clients').tagName).toBe('CODE');
    expect(unknown).toHaveTextContent('It ran nothing on the server and it can be wrong');
    expect(within(unknown).getByRole('button', { name: 'Ask Claude again' })).toBeInTheDocument();
  });

  it('offers no Ask Claude button until Claude Code is signed in, and says how to get one', async () => {
    stubApi({
      '/explain': { installed: true, method: 'none', signed_in: false, user: 'seed' },
      '/problems': problems(),
    });
    renderAt(<ProblemsCard />);
    const card = await screen.findByRole('region', { name: 'Problems in app logs' });
    await waitFor(() => expect(card).toHaveTextContent('Have Claude explain an issue'));
    expect(card).toHaveTextContent('signed in for seed (it is installed, but not signed in)');
    expect(card).toHaveTextContent('claude auth login');
    expect(within(card).queryByRole('button', { name: 'Ask Claude' })).toBeNull();
  });

  it('reads the logs again on request', async () => {
    let reads = 0;
    const api = stubApi({ '/problems': () => (reads++ === 0 ? problems() : { ...problems(), containers: [] }) });
    renderAt(<ProblemsCard />);
    await screen.findByRole('article', { name: 'Autoscan is holding back every scan' });
    fireEvent.click(screen.getByRole('button', { name: 'Check again' }));
    await waitFor(() => expect(screen.queryAllByRole('article')).toHaveLength(0));
    expect(api).toHaveBeenCalledWith('/api/problems?refresh=true', expect.anything());
  });
});
