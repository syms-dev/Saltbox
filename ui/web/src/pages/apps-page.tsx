import { useMemo, useState } from 'react';

import { formatWhen } from '../format';
import { Link, useNavigate } from 'react-router-dom';

import { useApps, useCheckUpdates, useUpdateAll, useUpdateApp, useUpdates } from '../api/queries';
import type { App } from '../api/types';
import { OpenLinks, UpdateBadge, overallUpdate } from '../components/app-links';
import { ErrorMessage, Loading } from '../components/query-state';
import { StatusBadge } from '../components/status-badge';
import styles from './apps-page.module.css';

type Filter = 'all' | 'installed' | 'saltbox' | 'sandbox';

const FILTERS: { label: string; value: Filter }[] = [
  { label: 'All', value: 'all' },
  { label: 'Installed', value: 'installed' },
  { label: 'Saltbox', value: 'saltbox' },
  { label: 'Sandbox', value: 'sandbox' },
];

export function matchesApp(app: App, needle: string, filter: Filter, category: string): boolean {
  if (filter === 'installed' && !app.installed) return false;
  if ((filter === 'saltbox' || filter === 'sandbox') && app.repo !== filter) return false;
  if (category !== '' && !app.categories.includes(category)) return false;
  if (needle === '') return true;
  const haystack = `${app.title} ${app.role} ${app.summary} ${app.categories.join(' ')}`.toLowerCase();
  return haystack.includes(needle.toLowerCase());
}

export function AppsPage(): React.ReactNode {
  const apps = useApps();
  const [needle, setNeedle] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [category, setCategory] = useState('');
  const categories = useMemo(
    () => Array.from(new Set((apps.data ?? []).flatMap((app) => app.categories))).sort(),
    [apps.data],
  );
  if (apps.isPending) return <Loading what="apps" />;
  if (apps.isError) return <ErrorMessage error={apps.error} prefix="Apps" />;
  const shown = apps.data
    .filter((app) => matchesApp(app, needle, filter, category))
    .sort((a, b) => a.title.localeCompare(b.title));
  const installed = apps.data.filter((app) => app.installed);
  return (
    <div className="stack">
      <h1>Apps</h1>
      <div className="row">
        <input
          aria-label="Filter apps"
          onChange={(event) => setNeedle(event.target.value)}
          placeholder="Filter by name or description"
          type="search"
          value={needle}
        />
        <select aria-label="Show" onChange={(event) => setFilter(event.target.value as Filter)} value={filter}>
          {FILTERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select aria-label="Category" onChange={(event) => setCategory(event.target.value)} value={category}>
          <option value="">Any category</option>
          {categories.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <span className="muted">
          {shown.length} of {apps.data.length} apps, {installed.length} installed
        </span>
      </div>
      {installed.length > 0 && filter === 'all' && needle === '' && category === '' ? (
        <InstalledApps apps={installed} />
      ) : null}
      <div className="grid">
        {shown.map((app) => (
          <Link
            className={`card ${styles['tile']}`}
            key={`${app.repo}/${app.role}`}
            to={`/apps/${app.repo}/${app.role}`}
          >
            <div className="row">
              <strong>{app.title}</strong>
              {app.installed ? <StatusBadge label="installed" status="succeeded" /> : null}
              {app.repo === 'sandbox' ? <StatusBadge label="sandbox" status="pending" /> : null}
            </div>
            <p className={`muted ${styles['summary']}`}>{app.summary === '' ? app.role : app.summary}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}

function checkedLabel(checkedAt: number | null, running: boolean): string {
  if (running) return 'Checking for updates…';
  if (checkedAt === null) return 'Not checked for updates yet';
  return `Updates checked ${formatWhen(new Date(checkedAt * 1000).toISOString())}`;
}

type InstalledAppsProps = { apps: App[] };

function InstalledApps({ apps }: InstalledAppsProps): React.ReactNode {
  const updates = useUpdates();
  const check = useCheckUpdates();
  const updateOne = useUpdateApp();
  const updateAll = useUpdateAll();
  const navigate = useNavigate();
  const pending = apps.filter((app) => app.update_available);
  const busy = updateOne.isPending || updateAll.isPending;
  const error = updateOne.error ?? updateAll.error ?? check.error;

  function runUpdate(app: App): void {
    if (!window.confirm(`Update ${app.title}? It restarts for a minute or two while the new image is installed.`)) {
      return;
    }
    updateOne.mutate({ repo: app.repo, role: app.role }, { onSuccess: (job) => void navigate(`/jobs/${job.id}`) });
  }

  function runAll(): void {
    const names = pending.map((app) => app.title).join(', ');
    if (!window.confirm(`Update ${names}? Each restarts for a minute or two.`)) return;
    updateAll.mutate(undefined, { onSuccess: (job) => void navigate(`/jobs/${job.id}`) });
  }

  return (
    <section aria-labelledby="installed-apps" className="card">
      <div className={`row ${styles['installedHeader']}`}>
        <h2 className={styles['installedTitle']} id="installed-apps">
          Installed
        </h2>
        <span className="muted">{checkedLabel(updates.data?.checked_at ?? null, updates.data?.running ?? false)}</span>
        <button
          disabled={check.isPending || updates.data?.running === true}
          onClick={() => check.mutate()}
          type="button"
        >
          Check now
        </button>
        {pending.length > 0 ? (
          <button className="primary" disabled={busy} onClick={runAll} type="button">
            Update all ({pending.length})
          </button>
        ) : null}
      </div>
      {error !== null ? <ErrorMessage error={error} /> : null}
      <table>
        <thead>
          <tr>
            <th>App</th>
            <th>Containers</th>
            <th>Updates</th>
          </tr>
        </thead>
        <tbody>
          {apps.map((app) => {
            const state = overallUpdate(app.containers.map((c) => c.update));
            return (
              <tr key={`${app.repo}/${app.role}`}>
                <td>
                  <div className={styles['appCell']}>
                    <Link to={`/apps/${app.repo}/${app.role}`}>{app.title}</Link>
                    <OpenLinks urls={app.urls.slice(0, 1)} />
                  </div>
                </td>
                <td>
                  <div className="row">
                    {app.containers.length === 0 ? (
                      <span className="muted">none</span>
                    ) : (
                      app.containers.map((c) => (
                        <StatusBadge
                          key={c.name}
                          label={`${c.name} ${c.health ?? c.status}`}
                          status={c.health ?? c.status}
                        />
                      ))
                    )}
                  </div>
                </td>
                <td>
                  <div className="row">
                    <UpdateBadge
                      detail={app.containers
                        .map((c) => c.update_detail)
                        .filter(Boolean)
                        .join('; ')}
                      state={state}
                    />
                    {state === 'update' ? (
                      <button disabled={busy} onClick={() => runUpdate(app)} type="button">
                        Update
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
