import { useQueryClient } from '@tanstack/react-query';
import { LoaderCircle, LogIn } from 'lucide-react';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import styles from './connection.module.css';
import { useToast } from './feedback';

/** Why the server is about to stop answering: it is rebooting, or the proxy in front of it is. */
export type Outage = 'proxy' | 'reboot' | 'update';
export type Reach = 'offline' | 'online' | 'signin';
/** What a probe found: whether the daemon answered, and which run of it did. */
export type Probe = { instance?: string | undefined; reach: Reach };

const BASE = '/api';
const POLL_ONLINE_MS = 10_000;
const POLL_OFFLINE_MS = 3_000;
const EXPECTED_FOR_MS = 120_000;
const RELOAD_GUARD_MS = 30_000;
const RELOAD_KEY = 'saltbox-ui:reloaded-for-sign-in';
const HINT_AFTER_SECONDS = 90;

/** Ask the daemon whether it is there, without following a redirect to the sign-in page. */
export async function probe(): Promise<Probe> {
  try {
    const response = await fetch(`${BASE}/meta`, {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
      redirect: 'manual',
    });
    // Single sign-on answers a lapsed session with a redirect to its own page, or a 401.
    if (response.type === 'opaqueredirect' || response.status === 401) return { reach: 'signin' };
    // 403 is the daemon itself refusing this user: it is up, and the page says why.
    if (response.status === 403) return { reach: 'online' };
    if (!response.ok) return { reach: 'offline' };
    // When the daemon started tells one run of it from the next.
    const meta = (await response.json()) as { started_at?: number };
    return { instance: meta.started_at === undefined ? undefined : String(meta.started_at), reach: 'online' };
  } catch {
    return { reach: 'offline' };
  }
}

/** "2m 14s", "45s". */
export function elapsed(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return whole >= 60 ? `${Math.floor(whole / 60)}m ${whole % 60}s` : `${whole}s`;
}

type Connection = {
  expectOutage: (kind: Outage) => void;
  expected: Outage | null;
  offlineSince: number | null;
  signedOut: boolean;
};

const NOT_WATCHING: Connection = {
  expectOutage: () => undefined,
  expected: null,
  offlineSince: null,
  signedOut: false,
};

const ConnectionContext = createContext<Connection>(NOT_WATCHING);

/** The state of the link to the server; a no-op outside the provider (single components in tests). */
export function useConnection(): Connection {
  return useContext(ConnectionContext);
}

function lastReload(): number {
  try {
    return Number(window.sessionStorage.getItem(RELOAD_KEY) ?? 0);
  } catch {
    return 0;
  }
}

/** Reload so the browser goes through the sign-in page. Once, so a sign-in page that is
 * itself still starting does not make the page spin. Returns whether it reloaded. */
function reloadForSignIn(): boolean {
  if (Date.now() - lastReload() < RELOAD_GUARD_MS) return false;
  try {
    window.sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
  } catch {
    // Storage is blocked: reload anyway.
  }
  window.location.reload();
  return true;
}

/**
 * Keeps asking the server whether it is there. When it stops answering (a reboot, Traefik or
 * Authelia being recreated) the page says so and keeps trying; when it answers again every
 * query is refreshed, and if the sign-in was lost on the way the page reloads to get it back.
 */
export function ConnectionProvider({
  children,
  check = probe,
}: {
  check?: () => Promise<Probe | Reach>;
  children: React.ReactNode;
}): React.ReactNode {
  const client = useQueryClient();
  const toast = useToast();
  const [offlineSince, setOfflineSince] = useState<number | null>(null);
  const [expected, setExpected] = useState<{ at: number; kind: Outage } | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  // The polling loop reads the latest state through refs, so it is started once.
  const state = useRef<{
    expected: typeof expected;
    failures: number;
    instance: string | undefined;
    offlineSince: number | null;
  }>({ expected, failures: 0, instance: undefined, offlineSince });
  const pollSoon = useRef<() => void>(() => undefined);
  useEffect(() => {
    state.current.expected = expected;
    state.current.offlineSince = offlineSince;
  }, [expected, offlineSince]);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function tick(): Promise<void> {
      const found = await check();
      if (stopped) return;
      const { instance, reach } = typeof found === 'string' ? { instance: undefined, reach: found } : found;
      const now = Date.now();
      const current = state.current;
      const disturbed = current.offlineSince !== null || current.expected !== null;
      if (reach === 'online') {
        current.failures = 0;
        setSignedOut(false);
        const restarted = instance !== undefined && current.instance !== undefined && instance !== current.instance;
        current.instance = instance ?? current.instance;
        if (restarted && current.expected?.kind === 'update') {
          // The app updated itself: this page is the old version, so load the new one.
          window.location.reload();
          return;
        }
        if (restarted && current.offlineSince === null) void client.invalidateQueries();
        if (current.offlineSince !== null) {
          const seconds = (now - current.offlineSince) / 1000;
          setOfflineSince(null);
          setExpected(null);
          void client.invalidateQueries();
          toast({ title: `The server is back after ${elapsed(seconds)}`, tone: 'ok' });
        } else if (current.expected !== null && now - current.expected.at > EXPECTED_FOR_MS) {
          setExpected(null); // it never went down
        }
      } else if (reach === 'signin') {
        // After an outage, getting the sign-in back is part of coming back by itself.
        if (!(disturbed && reloadForSignIn())) setSignedOut(true);
      } else {
        current.failures += 1;
        // One lost request is not an outage, unless one was announced.
        if ((current.failures >= 2 || current.expected !== null) && current.offlineSince === null) {
          setOfflineSince(now);
        }
      }
      const waiting = reach !== 'online' || current.expected !== null;
      timer = setTimeout(() => void tick(), waiting ? POLL_OFFLINE_MS : POLL_ONLINE_MS);
    }

    timer = setTimeout(() => void tick(), POLL_OFFLINE_MS);
    pollSoon.current = () => {
      clearTimeout(timer);
      timer = setTimeout(() => void tick(), POLL_OFFLINE_MS);
    };
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [check, client, toast]);

  const expectOutage = useCallback((kind: Outage) => {
    const announced = { at: Date.now(), kind };
    state.current.expected = announced;
    setExpected(announced);
    pollSoon.current(); // do not wait out the slow poll: the outage is about to start
  }, []);
  const value = useMemo(
    () => ({ expectOutage, expected: expected?.kind ?? null, offlineSince, signedOut }),
    [expectOutage, expected, offlineSince, signedOut],
  );
  return <ConnectionContext.Provider value={value}>{children}</ConnectionContext.Provider>;
}

const WAITING: Record<Outage | 'unknown', string> = {
  update: 'Saltbox UI is restarting on its new version. This page reloads by itself.',
  proxy: 'The proxy in front of this page is restarting. It reconnects by itself.',
  reboot: 'The server is restarting. This page reconnects by itself.',
  unknown: 'Lost contact with the server. Trying again every few seconds.',
};

/** What the page says while the server is away, about to be, or has lost the sign-in. */
export function ConnectionBanner(): React.ReactNode {
  const { expected, offlineSince, signedOut } = useConnection();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (offlineSince === null) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [offlineSince]);

  if (signedOut && offlineSince === null) {
    return (
      <p className={`note warn ${styles['banner']}`} role="status">
        <LogIn aria-hidden="true" size={16} />
        <span className={styles['text']}>You have been signed out.</span>
        <button className="small" onClick={() => window.location.reload()} type="button">
          Sign in again
        </button>
      </p>
    );
  }
  if (offlineSince !== null) {
    const seconds = Math.max(0, (now - offlineSince) / 1000);
    return (
      <p className={`note warn ${styles['banner']}`} role="status">
        <LoaderCircle aria-hidden="true" className="spin" size={16} />
        <span className={styles['text']}>
          {WAITING[expected ?? 'unknown']}
          {expected === null && seconds > HINT_AFTER_SECONDS ? (
            <>
              {' '}
              If it stays away, check <code>systemctl status saltbox-ui</code> on the server.
            </>
          ) : null}
        </span>
        <span className={styles['time']}>{elapsed(seconds)}</span>
      </p>
    );
  }
  if (expected === 'reboot') {
    return (
      <p className={`note ${styles['banner']}`} role="status">
        <LoaderCircle aria-hidden="true" className="spin" size={16} />
        <span className={styles['text']}>Restart requested. The server goes down in a moment.</span>
      </p>
    );
  }
  return null;
}

const STARTED_RECENTLY_SECONDS = 600;

/** After a boot: how the apps are coming back, until they all have or ten minutes pass. */
export function StartupBanner({
  running,
  total,
  uptime,
}: {
  running: number;
  total: number;
  uptime: number | null | undefined;
}): React.ReactNode {
  if (uptime === null || uptime === undefined || uptime > STARTED_RECENTLY_SECONDS || total === 0) return null;
  const minutes = Math.floor(uptime / 60);
  const ago = minutes < 1 ? 'less than a minute ago' : `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  return running >= total ? (
    <p className={`note ok ${styles['banner']}`} role="status">
      <span className={styles['text']}>
        The server started {ago} and all {total} containers are running.
      </span>
    </p>
  ) : (
    <p className={`note ${styles['banner']}`} role="status">
      <LoaderCircle aria-hidden="true" className="spin" size={16} />
      <span className={styles['text']}>
        The server started {ago}: {running} of {total} containers are running so far.
      </span>
    </p>
  );
}
