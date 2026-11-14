import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ProfileUse, RecyclarrStatus } from '../api/types';
import { renderAt, stubApi } from '../test-utils';
import { RecyclarrCard, profileLine } from './recyclarr-card';

const WEB = { default: true, name: 'WEB-1080p', summary: '1080p from streaming services.', trash_id: 'aaa' };
const HD = { default: true, name: 'HD Bluray + WEB', summary: '1080p Blu-ray and streaming.', trash_id: 'bbb' };

const STATUS: RecyclarrStatus = {
  config_exists: true,
  installed: true,
  instances: { radarr: ['radarr'], sonarr: ['sonarr'] },
  last_job: null,
  managed: true,
  profiles: { radarr: [HD], sonarr: [WEB] },
  running: true,
  selected: { radarr: ['bbb'], sonarr: ['aaa'] },
};

const SONARR: ProfileUse = {
  app: 'sonarr',
  missing: [],
  name: 'sonarr',
  noun: 'series',
  profiles: [
    { count: 0, id: 9, name: 'WEB-1080p', synced: true },
    { count: 120, id: 4, name: 'HD-1080p', synced: false },
    { count: 23, id: 1, name: 'Any', synced: false },
    { count: 0, id: 2, name: 'SD', synced: false },
  ],
  total: 143,
};

const RADARR: ProfileUse = {
  app: 'radarr',
  missing: ['HD Bluray + WEB'],
  name: 'radarr',
  noun: 'films',
  profiles: [{ count: 12, id: 1, name: 'Any', synced: false }],
  total: 12,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function routes(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    '/apps': [],
    '/jobs': { busy: false, current: null, jobs: [], lock: null },
    '/recyclarr': STATUS,
    '/recyclarr/usage': { instances: [SONARR, RADARR] },
    ...extra,
  };
}

describe('profile use', () => {
  it('lists only the profiles something is on', () => {
    expect(profileLine(SONARR)).toBe('120 on HD-1080p, 23 on Any');
    expect(profileLine({ app: 'sonarr', name: 'sonarr' })).toBe('');
  });

  it('says that a sync alone moved nothing, and what is still missing', async () => {
    stubApi(routes());
    renderAt(<RecyclarrCard />);
    const card = await screen.findByRole('region', { name: 'Quality profiles' });
    await waitFor(() => expect(card).toHaveTextContent('In use'));
    expect(card).toHaveTextContent('it does not put any show or film on them');
    expect(card).toHaveTextContent('Sonarr 143 series: 120 on HD-1080p, 23 on Any');
    expect(card).toHaveTextContent('Nothing uses WEB-1080p yet.');
    expect(card).toHaveTextContent('HD Bluray + WEB is not in Radarr yet. Press “Sync now” above to create it.');
    // Nothing to move films to until the profile exists.
    expect(within(card).queryByRole('button', { name: /Move all films/ })).toBeNull();
  });

  it('moves everything onto the synced profile after confirming', async () => {
    const moved: ProfileUse = {
      ...SONARR,
      profiles: [
        { count: 143, id: 9, name: 'WEB-1080p', synced: true },
        { count: 0, id: 4, name: 'HD-1080p', synced: false },
      ],
    };
    const api = stubApi(
      routes({
        'POST /recyclarr/assign': {
          moved: 143,
          profile: 'WEB-1080p',
          total: 143,
          usage: { instances: [moved, RADARR] },
        },
      }),
    );
    renderAt(<RecyclarrCard />);
    fireEvent.click(await screen.findByRole('button', { name: 'Move all series to WEB-1080p' }));
    const dialog = await screen.findByRole('dialog', { name: 'Use WEB-1080p for everything in Sonarr?' });
    expect(dialog).toHaveTextContent('Changes the quality profile of 143 series in Sonarr to WEB-1080p');
    expect(dialog).toHaveTextContent('Nothing is downloaded now.');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Move 143 series' }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        '/api/recyclarr/assign',
        expect.objectContaining({ body: JSON.stringify({ instance: 'sonarr', profile_id: 9 }), method: 'POST' }),
      ),
    );
    expect(await screen.findByText('143 series in Sonarr now use WEB-1080p')).toBeInTheDocument();
    const card = screen.getByRole('region', { name: 'Quality profiles' });
    await waitFor(() => expect(card).toHaveTextContent('Everything uses WEB-1080p.'));
    expect(within(card).queryByRole('button', { name: /Move all series/ })).toBeNull();
  });

  it('says so when an app does not answer', async () => {
    stubApi(routes({ '/recyclarr/usage': { instances: [{ app: 'radarr', error: 'radarr: 503', name: 'radarr' }] } }));
    renderAt(<RecyclarrCard />);
    const card = await screen.findByRole('region', { name: 'Quality profiles' });
    await waitFor(() => expect(card).toHaveTextContent('Radarr did not answer: radarr: 503'));
  });
});
