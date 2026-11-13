import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  ConnectionBanner,
  ConnectionProvider,
  type Reach,
  StartupBanner,
  elapsed,
  probe,
  useConnection,
} from './connection';
import { FeedbackProvider } from './feedback';

function response(status: number, type: ResponseType = 'basic'): Response {
  return { ok: status >= 200 && status < 300, status, type } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('probe', () => {
  it('tells a server that is away from one that wants a sign-in', async () => {
    const answers: (Response | Error)[] = [
      response(200),
      response(403), // the daemon refusing this user is still the daemon answering
      response(502),
      response(404),
      response(401),
      response(0, 'opaqueredirect'),
      new TypeError('Failed to fetch'),
    ];
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        const next = answers.shift();
        return next instanceof Error ? Promise.reject(next) : Promise.resolve(next);
      }),
    );
    const seen: Reach[] = [];
    for (let i = 0; i < 7; i++) seen.push(await probe());
    expect(seen).toEqual(['online', 'online', 'offline', 'offline', 'signin', 'signin', 'offline']);
    expect(fetch).toHaveBeenCalledWith('/api/meta', expect.objectContaining({ cache: 'no-store', redirect: 'manual' }));
  });

  it('formats how long it took', () => {
    expect(elapsed(45.2)).toBe('45s');
    expect(elapsed(134)).toBe('2m 14s');
  });
});

describe('ConnectionProvider', () => {
  let reach: Reach;
  let refreshed: ReturnType<typeof vi.fn<() => void>>;
  let expectOutage: (kind: 'proxy' | 'reboot') => void;

  function Announce(): React.ReactNode {
    const connection = useConnection();
    expectOutage = connection.expectOutage;
    return null;
  }

  function mount(): void {
    const client = new QueryClient();
    refreshed = vi.fn<() => void>();
    vi.spyOn(client, 'invalidateQueries').mockImplementation(() => {
      refreshed();
      return Promise.resolve();
    });
    render(
      <QueryClientProvider client={client}>
        <FeedbackProvider>
          <ConnectionProvider check={() => Promise.resolve(reach)}>
            <Announce />
            <ConnectionBanner />
          </ConnectionProvider>
        </FeedbackProvider>
      </QueryClientProvider>,
    );
  }

  async function wait(ms: number): Promise<void> {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  beforeEach(() => {
    vi.useFakeTimers();
    reach = 'online';
  });

  it('waits out an outage, counts the time, and refreshes everything when the server is back', async () => {
    mount();
    await wait(3_000);
    expect(screen.queryByText(/Lost contact|restarting/)).toBeNull();

    reach = 'offline';
    await wait(10_000); // one lost request is not an outage
    expect(screen.queryByText(/Lost contact/)).toBeNull();
    await wait(3_000);
    expect(screen.getByText(/Lost contact with the server/)).toBeInTheDocument();
    await wait(20_000);
    expect(screen.getByText('20s')).toBeInTheDocument();
    expect(refreshed).not.toHaveBeenCalled();

    reach = 'online';
    await wait(3_000);
    expect(screen.queryByText(/Lost contact/)).toBeNull();
    expect(screen.getByText(/The server is back after 2\ds/)).toBeInTheDocument();
    expect(refreshed).toHaveBeenCalledTimes(1);
  });

  it('says a restart is coming, then that it is happening, when one was asked for', async () => {
    mount();
    await wait(3_000);
    act(() => expectOutage('reboot'));
    expect(screen.getByText('Restart requested. The server goes down in a moment.')).toBeInTheDocument();
    reach = 'offline';
    await wait(3_000); // announced, so the first lost request counts
    expect(screen.getByText(/The server is restarting. This page reconnects by itself./)).toBeInTheDocument();
    reach = 'online';
    await wait(3_000);
    expect(screen.queryByText(/The server is restarting/)).toBeNull();
    expect(screen.queryByText(/Restart requested/)).toBeNull();
  });

  it('reloads to sign in again after an outage, and only asks when nothing else happened', async () => {
    const reload = vi.fn();
    vi.stubGlobal('location', { href: window.location.href, reload });
    window.sessionStorage.clear();
    mount();
    await wait(3_000);
    reach = 'signin';
    await wait(10_000);
    expect(reload).not.toHaveBeenCalled(); // not in the middle of whatever the person is doing
    expect(screen.getByText('You have been signed out.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in again' })).toBeInTheDocument();

    act(() => expectOutage('proxy'));
    await wait(3_000);
    expect(reload).toHaveBeenCalledTimes(1);
    await wait(9_000);
    expect(reload).toHaveBeenCalledTimes(1); // once, not on every poll
  });
});

describe('StartupBanner', () => {
  it('follows the apps coming back after a boot, and goes away after ten minutes', () => {
    const { rerender } = render(<StartupBanner running={18} total={25} uptime={150} />);
    expect(screen.getByRole('status')).toHaveTextContent(
      'The server started 2 minutes ago: 18 of 25 containers are running so far.',
    );
    rerender(<StartupBanner running={25} total={25} uptime={240} />);
    expect(screen.getByRole('status')).toHaveTextContent(
      'The server started 4 minutes ago and all 25 containers are running.',
    );
    rerender(<StartupBanner running={25} total={25} uptime={601} />);
    expect(screen.queryByRole('status')).toBeNull();
    rerender(<StartupBanner running={3} total={25} uptime={null} />);
    expect(screen.queryByRole('status')).toBeNull();
  });
});
