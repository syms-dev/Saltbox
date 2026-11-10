import {
  ArrowUpCircle,
  ChevronRight,
  ExternalLink,
  LoaderCircle,
  PackagePlus,
  RefreshCw,
  RotateCw,
  Search,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { useApps, useCheckUpdates, useJobs, useUpdates } from '../api/queries';
import type { App } from '../api/types';
import { AppAvatar } from '../components/app-avatar';
import { ErrorMessage, Loading } from '../components/query-state';
import { StatusDot } from '../components/status-dot';
import { formatRelative } from '../format';
import { useContainerActions, useJobActions } from '../lib/actions';
import { appHealth, hostOf, needsAttention } from '../lib/status';
import styles from './apps-page.module.css';

// -- filtering (shared with tests) ---------------------------------------------------------
export type Source = 'all' | 'saltbox' | 'sandbox';

/** Search text across title, role, summary and categories, case-insensitively. */
export function matchesText(app: App, needle: string): boolean {
  if (needle.trim() === '') return true;
  const haystack = `${app.title} ${app.role} ${app.summary} ${app.categories.join(' ')}`.toLowerCase();
  return needle
    .toLowerCase()
    .split(/\s+/)
    .every((word) => haystack.includes(word));
}

export const GROUPS = [
  { label: 'Get content', value: 'Content Acquisition Apps' },
  { label: 'Watch & listen', value: 'Content Delivery Apps' },
  { label: 'Media extras', value: 'Accessories' },
  { label: 'Server admin', value: 'Admin Apps' },
  { label: 'Productivity', value: 'Productivity Apps' },
] as const;

/** A sensible first set for a media server; shown under "Popular". */
export const POPULAR = [
  'plex',
  'jellyfin',
  'emby',
  'sonarr',
  'radarr',
  'lidarr',
  'prowlarr',
  'bazarr',
  'qbittorrent',
  'sabnzbd',
  'seerr',
  'overseerr',
  'tautulli',
  'autoscan',
  'recyclarr',
  'notifiarr',
  'unpackerr',
  'readarr',
  'audiobookshelf',
  'homepage',
];

export function subcategory(app: App): string {
  const category = app.categories[0] ?? '';
  return category.split(' > ').slice(1).join(' › ');
}

export function inGroup(app: App, group: string): boolean {
  if (group === '') return true;
  if (group === 'popular') return POPULAR.includes(app.role);
  return app.categories.some((c) => c.startsWith(`${group} >`) || c === group);
}

// -- installed ----------------------------------------------------------------------------------
type Show = 'all' | 'problems' | 'updates';

function InstalledRow({ app }: { app: App }): React.ReactNode {
  const jobs = useJobActions();
  const containers = useContainerActions();
  const busy = useJobs().data?.busy ?? false;
  const health = appHealth(app);
  const url = app.urls[0];
  const main = app.containers[0];
  return (
    <li className={styles['row']}>
      <Link aria-label={`${app.title} details`} className={styles['rowMain']} to={`/apps/${app.repo}/${app.role}`}>
        <AppAvatar title={app.title} url={url} />
        <span className={styles['rowText']}>
          <span className={styles['rowTitle']}>
            {app.title}
            {app.repo === 'sandbox' ? <span className={styles['tag']}>Sandbox</span> : null}
          </span>
          <span className={`muted small ${styles['rowSub']}`}>{url === undefined ? app.role : hostOf(url)}</span>
        </span>
      </Link>
      <span className={styles['rowStatus']}>
        <StatusDot health={health} />
        {app.containers.length > 1 ? <span className="muted small">{app.containers.length} containers</span> : null}
      </span>
      <span className={styles['rowUpdate']}>
        {app.update_available ? (
          <button className="small primary" disabled={busy} onClick={() => void jobs.updateApp(app)} type="button">
            <ArrowUpCircle aria-hidden="true" size={15} /> Update
          </button>
        ) : (
          <span className="muted small">{app.containers.some((c) => c.update === 'current') ? 'Up to date' : ''}</span>
        )}
      </span>
      <span className={styles['rowActions']}>
        {url === undefined ? null : (
          <a
            aria-label={`Open ${app.title}`}
            className="button small ghost"
            href={url}
            rel="noreferrer"
            target="_blank"
          >
            <ExternalLink aria-hidden="true" size={15} /> Open
          </a>
        )}
        {main === undefined ? null : (
          <button
            aria-label={`Restart ${app.title}`}
            className="small ghost icon"
            disabled={containers.pending}
            onClick={() => void containers.run(main.name, main.status === 'running' ? 'restart' : 'start')}
            title={main.status === 'running' ? 'Restart' : 'Start'}
            type="button"
          >
            <RotateCw aria-hidden="true" size={15} />
          </button>
        )}
        <Link aria-hidden="true" className="button small ghost icon" tabIndex={-1} to={`/apps/${app.repo}/${app.role}`}>
          <ChevronRight size={16} />
        </Link>
      </span>
    </li>
  );
}

function Installed({ apps }: { apps: App[] }): React.ReactNode {
  const [params, setParams] = useSearchParams();
  const [needle, setNeedle] = useState('');
  const show = (params.get('show') ?? 'all') as Show;
  const updates = useUpdates();
  const check = useCheckUpdates();
  const jobs = useJobActions();
  const pending = apps.filter((app) => app.update_available);
  const problems = apps.filter(needsAttention);
  const base = show === 'updates' ? pending : show === 'problems' ? problems : apps;
  const shown = base.filter((app) => matchesText(app, needle)).sort((a, b) => a.title.localeCompare(b.title));
  const checking = check.isPending || updates.data?.running === true;
  const chip = (value: Show, label: string, count: number): React.ReactNode => (
    <button
      aria-pressed={show === value}
      className="chip"
      onClick={() => setParams(value === 'all' ? {} : { show: value }, { replace: true })}
      type="button"
    >
      {label} <span className="count">{count}</span>
    </button>
  );
  return (
    <div className="stack">
      <div className={styles['toolbar']}>
        <label className={styles['search']}>
          <Search aria-hidden="true" size={16} />
          <input
            aria-label="Filter installed apps"
            onChange={(e) => setNeedle(e.target.value)}
            placeholder="Filter"
            type="search"
            value={needle}
          />
        </label>
        <div className="chips">
          {chip('all', 'All', apps.length)}
          {chip('updates', 'Updates', pending.length)}
          {chip('problems', 'Needs attention', problems.length)}
        </div>
        <span className="spacer" />
        <span className="muted small">
          {checking
            ? 'Checking for updates…'
            : updates.data?.checked_at == null
              ? 'Updates not checked yet'
              : `Updates checked ${formatRelative(updates.data.checked_at)}`}
        </span>
        <button className="small" disabled={checking} onClick={() => check.mutate()} type="button">
          {checking ? (
            <LoaderCircle aria-hidden="true" className="spin" size={15} />
          ) : (
            <RefreshCw aria-hidden="true" size={15} />
          )}{' '}
          Check now
        </button>
        {pending.length > 0 ? (
          <button className="small primary" onClick={() => void jobs.updateAll(pending)} type="button">
            Update all ({pending.length})
          </button>
        ) : null}
      </div>
      {check.isError ? <ErrorMessage error={check.error} /> : null}
      {shown.length === 0 ? (
        <div className="card empty">
          {apps.length === 0 ? (
            <>
              <p>No apps installed yet.</p>
              <Link className="button primary" to="/apps/discover">
                Browse the catalog
              </Link>
            </>
          ) : show === 'updates' ? (
            <p>Every app is up to date.</p>
          ) : show === 'problems' ? (
            <p>Every app is running normally.</p>
          ) : (
            <p>No installed app matches “{needle}”.</p>
          )}
        </div>
      ) : (
        <ul aria-label="Installed apps" className={`card ${styles['list']}`}>
          {shown.map((app) => (
            <InstalledRow app={app} key={`${app.repo}/${app.role}`} />
          ))}
        </ul>
      )}
    </div>
  );
}

// -- discover ---------------------------------------------------------------------------------
function Discover({ apps }: { apps: App[] }): React.ReactNode {
  const [needle, setNeedle] = useState('');
  const [group, setGroup] = useState<string>('popular');
  const [sub, setSub] = useState('');
  const [source, setSource] = useState<Source>('all');
  const [hideInstalled, setHideInstalled] = useState(false);
  const jobs = useJobActions();
  const busy = useJobs().data?.busy ?? false;

  const searching = needle.trim() !== '';
  const subs = useMemo(
    () =>
      Array.from(new Set(apps.filter((app) => inGroup(app, group === 'popular' ? '' : group)).map(subcategory)))
        .filter(Boolean)
        .sort(),
    [apps, group],
  );
  const shown = apps
    .filter((app) => (searching ? true : inGroup(app, group)))
    .filter((app) => sub === '' || subcategory(app) === sub)
    .filter((app) => source === 'all' || app.repo === source)
    .filter((app) => !hideInstalled || !app.installed)
    .filter((app) => matchesText(app, needle))
    .sort((a, b) =>
      group === 'popular' && !searching
        ? POPULAR.indexOf(a.role) - POPULAR.indexOf(b.role)
        : a.title.localeCompare(b.title),
    );

  return (
    <div className="stack">
      <div className={styles['toolbar']}>
        <label className={`${styles['search']} ${styles['searchWide']}`}>
          <Search aria-hidden="true" size={16} />
          <input
            aria-label="Search the catalog"
            onChange={(e) => setNeedle(e.target.value)}
            placeholder={`Search ${apps.length} apps by name, purpose or category`}
            type="search"
            value={needle}
          />
        </label>
      </div>
      <div className={styles['toolbar']}>
        <div aria-label="Categories" className="chips" role="group">
          {[{ label: 'Popular', value: 'popular' }, ...GROUPS, { label: 'Everything', value: '' }].map((g) => (
            <button
              aria-pressed={!searching && group === g.value}
              className="chip"
              key={g.value}
              onClick={() => {
                setGroup(g.value);
                setSub('');
                setNeedle('');
              }}
              type="button"
            >
              {g.label}
            </button>
          ))}
        </div>
      </div>
      <div className={styles['toolbar']}>
        {subs.length > 1 && group !== 'popular' ? (
          <select aria-label="Kind of app" onChange={(e) => setSub(e.target.value)} value={sub}>
            <option value="">Any kind</option>
            {subs.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        ) : null}
        <select aria-label="Source" onChange={(e) => setSource(e.target.value as Source)} value={source}>
          <option value="all">Saltbox and Sandbox</option>
          <option value="saltbox">Saltbox only</option>
          <option value="sandbox">Sandbox only</option>
        </select>
        <label className="row small">
          <input checked={hideInstalled} onChange={(e) => setHideInstalled(e.target.checked)} type="checkbox" /> Hide
          installed
        </label>
        <span className="spacer" />
        <span className="muted small">{shown.length} apps</span>
      </div>
      {shown.length === 0 ? (
        <div className="card empty">
          <p>Nothing matches. Try another word or category.</p>
        </div>
      ) : (
        <ul aria-label="Catalog" className={styles['catalog']}>
          {shown.map((app) => (
            <li className={`card ${styles['entry']}`} key={`${app.repo}/${app.role}`}>
              <div className={styles['entryHead']}>
                <AppAvatar title={app.title} />
                <div className={styles['entryTitle']}>
                  <Link to={`/apps/${app.repo}/${app.role}`}>{app.title}</Link>
                  <span className="muted small">{subcategory(app) || 'App'}</span>
                </div>
                {app.repo === 'sandbox' ? <span className={styles['tag']}>Sandbox</span> : null}
              </div>
              <p className={styles['entrySummary']}>{app.summary === '' ? 'No description yet.' : app.summary}</p>
              <div className={styles['entryFoot']}>
                {app.installed ? (
                  <span className={styles['installed']}>Installed</span>
                ) : (
                  <button
                    className="small primary"
                    disabled={busy}
                    onClick={() => void jobs.install(app)}
                    type="button"
                  >
                    <PackagePlus aria-hidden="true" size={15} /> Install
                  </button>
                )}
                {app.docs_url === '' ? null : (
                  <a className="small" href={app.docs_url} rel="noreferrer" target="_blank">
                    Docs
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// -- page ----------------------------------------------------------------------------------------
export function AppsPage({ tab }: { tab: 'discover' | 'installed' }): React.ReactNode {
  const apps = useApps();
  if (apps.isPending) return <Loading what="apps" />;
  if (apps.isError) return <ErrorMessage error={apps.error} prefix="Apps" />;
  const installed = apps.data.filter((app) => app.installed);
  return (
    <div className="stack">
      <div className={styles['header']}>
        <h1>Apps</h1>
        <span className="spacer" />
        <Link className="button small" to="/connect">
          Connect apps
        </Link>
      </div>
      <div className="tabs" role="tablist">
        <Link aria-selected={tab === 'installed'} className="tab" role="tab" to="/apps">
          Installed <span className="count">{installed.length}</span>
        </Link>
        <Link aria-selected={tab === 'discover'} className="tab" role="tab" to="/apps/discover">
          Discover <span className="count">{apps.data.length}</span>
        </Link>
      </div>
      {tab === 'installed' ? <Installed apps={installed} /> : <Discover apps={apps.data} />}
    </div>
  );
}
