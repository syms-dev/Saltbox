import {
  Activity,
  BellRing,
  Cable,
  FileCog,
  House,
  LayoutGrid,
  LoaderCircle,
  Search,
  Server,
  TriangleAlert,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet } from 'react-router-dom';

import { ApiError, apiFetch, API_ROUTES } from '../api/client';
import { useJobs, useMeta, useOverview } from '../api/queries';
import type { Job, Meta } from '../api/types';
import { formatDuration } from '../format';
import { CommandPalette } from './command-palette';
import { ConnectionBanner, StartupBanner, useConnection } from './connection';
import { useToast } from './feedback';
import styles from './shell.module.css';

const ICON = 18;

const NAV = [
  { icon: <House size={ICON} />, label: 'Home', short: 'Home', to: '/' },
  { icon: <LayoutGrid size={ICON} />, label: 'Apps', short: 'Apps', to: '/apps' },
  { icon: <Activity size={ICON} />, label: 'Activity', short: 'Activity', to: '/activity' },
  { icon: <Server size={ICON} />, label: 'System', short: 'System', to: '/system' },
  { icon: <BellRing size={ICON} />, label: 'Automation', short: 'Automation', to: '/automation' },
  { icon: <Cable size={ICON} />, label: 'Connect apps', short: 'Connect', to: '/connect' },
  { icon: <FileCog size={ICON} />, label: 'Config', short: 'Config', to: '/config' },
] as const;

/** The bottom bar has room for five; Connect and Automation are linked from Apps and System. */
const TABS = NAV.filter((item) => item.to !== '/connect' && item.to !== '/automation');

function navClass({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles['navLink']} ${styles['active']}` : (styles['navLink'] ?? '');
}

function tabClass({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles['tab']} ${styles['active']}` : (styles['tab'] ?? '');
}

/**
 * The foot of the sidebar: this app's name and version, and nothing else. Which commit and
 * branch Saltbox is on belongs with `sb update` on the System page, where it is shown.
 */
function Version({ meta }: { meta: Meta }): React.ReactNode {
  return (
    <span className={styles['version']}>
      <span>Saltbox UI</span>
      <span className={styles['versionNumber']}>{meta.version}</span>
    </span>
  );
}

/** "sb install sonarr" from a job, without the path to sb. */
export function jobTitle(job: Pick<Job, 'command_line'>): string {
  return job.command_line.replace(/^\S*\/(?=sb\b)/, '');
}

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent);

function RunningJob({ job }: { job: Job }): React.ReactNode {
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  const waiting = job.question != null;
  return (
    <Link className={styles['jobBanner']} to={`/activity/${job.id}`}>
      <LoaderCircle aria-hidden="true" className="spin" size={16} />
      <span className={styles['jobText']}>
        {waiting ? (
          <>
            <code>{jobTitle(job)}</code> is waiting for your answer
          </>
        ) : (
          <>
            Running <code>{jobTitle(job)}</code>
          </>
        )}
      </span>
      <span className={styles['jobTime']}>{formatDuration(job.started_at, null)}</span>
      <span className={styles['jobLink']}>{waiting ? 'Answer' : 'View log'}</span>
    </Link>
  );
}

/** Tell the person when a job they may have walked away from finishes. */
function useJobFinishedToast(current: Job | null): void {
  const toast = useToast();
  const previous = useRef<Job | null>(null);
  useEffect(() => {
    const before = previous.current;
    previous.current = current;
    if (before === null || current?.id === before.id) return;
    void apiFetch<Job>(API_ROUTES.job(before.id))
      .then((job) => {
        const ok = job.status === 'succeeded';
        toast({
          href: `/activity/${job.id}`,
          linkLabel: ok ? 'View log' : 'See what failed',
          title: `${jobTitle(job)} ${ok ? 'finished' : job.status}`,
          tone: ok ? 'ok' : 'danger',
        });
      })
      .catch(() => undefined);
  }, [current, toast]);
}

export function Shell(): React.ReactNode {
  const meta = useMeta();
  const jobs = useJobs();
  const overview = useOverview();
  const connection = useConnection();
  const [searching, setSearching] = useState(false);
  const current = jobs.data?.current ?? null;
  useJobFinishedToast(current);
  const closeSearch = useCallback(() => setSearching(false), []);

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      const typing = event.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
      if ((event.key === 'k' && (event.metaKey || event.ctrlKey)) || (event.key === '/' && !typing)) {
        event.preventDefault();
        setSearching(true);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const domain = meta.data?.domain ?? null;
  const updates = overview.data?.updates.pending.length ?? 0;
  const saltbox = overview.data?.updates.saltbox?.length ?? 0;
  const problems = (overview.data?.containers.unhealthy.length ?? 0) + (overview.data?.containers.stopped.length ?? 0);

  const searchButton = (
    <button className={styles['searchButton']} onClick={() => setSearching(true)} type="button">
      <Search aria-hidden="true" size={16} />
      <span className={styles['searchLabel']}>Search</span>
      <kbd className={styles['searchKey']}>{IS_MAC ? '⌘K' : 'Ctrl K'}</kbd>
    </button>
  );

  return (
    <div className={styles['shell']}>
      <aside className={styles['sidebar']}>
        <Link className={styles['brand']} to="/">
          <span aria-hidden="true" className={styles['mark']} />
          <span className={styles['brandText']}>
            <span className={styles['brandName']}>Saltbox</span>
            <span className={styles['brandDomain']}>{domain ?? 'server'}</span>
          </span>
        </Link>
        {searchButton}
        <nav aria-label="Main" className={styles['nav']}>
          {NAV.map((item) => (
            <NavLink className={navClass} end={item.to === '/'} key={item.to} to={item.to}>
              {item.icon}
              <span>{item.label}</span>
              {item.to === '/apps' && updates > 0 ? (
                <span className={styles['badge']} title="updates available">
                  {updates}
                </span>
              ) : null}
              {item.to === '/system' && saltbox > 0 ? (
                <span className={styles['badge']} title="Saltbox update available">
                  1
                </span>
              ) : null}
              {item.to === '/' && problems > 0 ? (
                <span className={`${styles['badge']} ${styles['badgeDanger']}`} title="apps need attention">
                  {problems}
                </span>
              ) : null}
            </NavLink>
          ))}
        </nav>
        <div className={styles['sidebarFoot']}>
          {meta.isError ? (
            <span className={styles['offline']}>
              <TriangleAlert size={14} /> Daemon unreachable
            </span>
          ) : (
            meta.data && <Version meta={meta.data} />
          )}
        </div>
      </aside>

      <header className={styles['topbar']}>
        <Link className={styles['brand']} to="/">
          <span aria-hidden="true" className={styles['mark']} />
          <span className={styles['brandName']}>{domain ?? 'Saltbox'}</span>
        </Link>
        {searchButton}
      </header>

      <main className={styles['main']}>
        {current === null ? null : <RunningJob job={current} />}
        <ConnectionBanner />
        {connection.offlineSince === null && overview.data !== undefined ? (
          <StartupBanner
            running={overview.data.containers.running}
            total={overview.data.containers.total}
            uptime={overview.data.host.uptime}
          />
        ) : null}
        {meta.error instanceof ApiError && meta.error.status === 403 ? (
          <p className="note danger" role="alert">
            Access refused: {meta.error.message}.
          </p>
        ) : null}
        <div className={styles['content']}>
          <Outlet />
        </div>
      </main>

      <nav aria-label="Main" className={styles['tabbar']}>
        {TABS.map((item) => (
          <NavLink className={tabClass} end={item.to === '/'} key={item.to} to={item.to}>
            {item.icon}
            <span>{item.short}</span>
          </NavLink>
        ))}
      </nav>

      {searching ? <CommandPalette onClose={closeSearch} /> : null}
    </div>
  );
}
