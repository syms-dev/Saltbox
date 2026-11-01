import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { useApps } from '../api/queries';
import type { App } from '../api/types';
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
        <section className="card">
          <h2>Installed</h2>
          <table>
            <thead>
              <tr>
                <th>App</th>
                <th>Instances</th>
                <th>Containers</th>
              </tr>
            </thead>
            <tbody>
              {installed.map((app) => (
                <tr key={`${app.repo}/${app.role}`}>
                  <td>
                    <Link to={`/apps/${app.repo}/${app.role}`}>{app.title}</Link>
                  </td>
                  <td>{app.instances.join(', ')}</td>
                  <td className="row">
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
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
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
