import {
  ArrowLeft,
  ArrowUpCircle,
  BookOpen,
  Copy,
  ExternalLink,
  PackagePlus,
  Play,
  RotateCw,
  CircleStop,
  Wrench,
} from 'lucide-react';
import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { useAppDetail, useContainerLogs, useJobs, useUpdateOverrides } from '../api/queries';
import type { App, AppDetail, ContainerState, Field } from '../api/types';
import { AppAvatar } from '../components/app-avatar';
import { UpdateBadge } from '../components/app-links';
import { useToast } from '../components/feedback';
import { LogView } from '../components/log-view';
import { ErrorMessage, Loading } from '../components/query-state';
import { StatusDot } from '../components/status-dot';
import { appTag, useContainerActions, useJobActions } from '../lib/actions';
import { appHealth, containerHealth, hostOf } from '../lib/status';
import styles from './app-page.module.css';

/** The parser keeps the whole `key: value` source line; show only the value part. */
export function defaultSource(field: Pick<Field, 'name' | 'raw' | 'value'>): string {
  if (field.raw === '') return formatValue(field.value);
  const prefix = `${field.name}:`;
  return field.raw.startsWith(prefix) ? field.raw.slice(prefix.length).trim() : field.raw;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

/** The detail record as the App shape the shared actions take. */
function asApp(detail: AppDetail, installed: boolean): App {
  return {
    ...detail.app,
    containers: detail.containers,
    installed,
    instances: detail.instances,
    update_available: detail.update_available,
    urls: detail.urls,
  };
}

// -- overview -------------------------------------------------------------------------------
function ContainerTable({ containers }: { containers: ContainerState[] }): React.ReactNode {
  const actions = useContainerActions();
  return (
    <table>
      <thead>
        <tr>
          <th>Container</th>
          <th>State</th>
          <th>Image</th>
          <th>Updates</th>
          <th>
            <span className="visually-hidden">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {containers.map((c) => (
          <tr key={c.name}>
            <td>
              <code>{c.name}</code>
            </td>
            <td>
              <StatusDot health={containerHealth(c)} />
            </td>
            <td className="muted">
              <code>{c.image}</code>
            </td>
            <td>
              <UpdateBadge detail={c.update_detail} state={c.update} />
            </td>
            <td>
              <div className="row">
                {c.status === 'running' ? (
                  <>
                    <button
                      className="small"
                      disabled={actions.pending}
                      onClick={() => void actions.run(c.name, 'restart')}
                      type="button"
                    >
                      <RotateCw aria-hidden="true" size={14} /> Restart
                    </button>
                    <button
                      className="small ghost"
                      disabled={actions.pending}
                      onClick={() => void actions.run(c.name, 'stop')}
                      type="button"
                    >
                      <CircleStop aria-hidden="true" size={14} /> Stop
                    </button>
                  </>
                ) : (
                  <button
                    className="small primary"
                    disabled={actions.pending}
                    onClick={() => void actions.run(c.name, 'start')}
                    type="button"
                  >
                    <Play aria-hidden="true" size={14} /> Start
                  </button>
                )}
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OverviewTab({ detail, installed }: { detail: AppDetail; installed: boolean }): React.ReactNode {
  const { app } = detail;
  const links = app.app_links.filter((link) => link.url !== '');
  return (
    <div className="stack">
      {installed ? (
        <section className="card">
          <h2>Containers</h2>
          {detail.containers.length === 0 ? (
            <p className="muted">
              No containers found for this app. If it should be running, reinstall it from the button above.
            </p>
          ) : (
            <ContainerTable containers={detail.containers} />
          )}
        </section>
      ) : (
        <section className="card">
          <h2>About {app.title}</h2>
          <p>{app.summary === '' ? 'No description in the Saltbox docs yet.' : app.summary}</p>
          <p className="muted small">
            Installing runs <code>sb install {appTag(asApp(detail, false))}</code>. You can set inventory overrides on
            the Settings tab first; they apply when it installs.
          </p>
        </section>
      )}
      <div className="grid">
        <section className="card">
          <h3>Addresses</h3>
          {detail.urls.length === 0 ? (
            <p className="muted small">
              {installed ? 'This app has no web address (it runs in the background).' : 'Appears once installed.'}
            </p>
          ) : (
            <ul className={styles['links']}>
              {detail.urls.map((url) => (
                <li key={url}>
                  <a href={url} rel="noreferrer" target="_blank">
                    {hostOf(url)} <ExternalLink aria-hidden="true" size={13} />
                  </a>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="card">
          <h3>Instances</h3>
          <p className="small">{detail.instances.join(', ')}</p>
          <p className="muted small">
            {app.supports_instances
              ? `Add more with ${app.role}_instances in the inventory (Settings tab).`
              : 'This role runs a single instance.'}
          </p>
        </section>
        <section className="card">
          <h3>Learn more</h3>
          <ul className={styles['links']}>
            {app.docs_url === '' ? null : (
              <li>
                <a href={app.docs_url} rel="noreferrer" target="_blank">
                  Saltbox docs <ExternalLink aria-hidden="true" size={13} />
                </a>
              </li>
            )}
            {app.link === '' ? null : (
              <li>
                <a href={app.link} rel="noreferrer" target="_blank">
                  Project website <ExternalLink aria-hidden="true" size={13} />
                </a>
              </li>
            )}
            {links.map((link) => (
              <li key={link.url}>
                <a href={link.url} rel="noreferrer" target="_blank">
                  {link.name} <ExternalLink aria-hidden="true" size={13} />
                </a>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

// -- logs --------------------------------------------------------------------------------------
const TAILS = [100, 300, 1000] as const;

function LogsTab({ containers }: { containers: ContainerState[] }): React.ReactNode {
  const [name, setName] = useState(containers[0]?.name ?? '');
  const [tail, setTail] = useState<number>(300);
  const [live, setLive] = useState(true);
  const [filter, setFilter] = useState('');
  const logs = useContainerLogs(name, tail, live);
  const toast = useToast();
  if (containers.length === 0) return <p className="muted">This app has no containers to read logs from.</p>;
  const lines = logs.data?.lines ?? [];
  return (
    <section className="card stack-sm">
      <div className="row">
        {containers.length > 1 ? (
          <select aria-label="Container" onChange={(e) => setName(e.target.value)} value={name}>
            {containers.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>
        ) : null}
        <select aria-label="Lines" onChange={(e) => setTail(Number(e.target.value))} value={tail}>
          {TAILS.map((n) => (
            <option key={n} value={n}>
              Last {n} lines
            </option>
          ))}
        </select>
        <input
          aria-label="Filter log lines"
          className={styles['filter']}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter lines"
          type="search"
          value={filter}
        />
        <label className="row small">
          <input checked={live} onChange={(e) => setLive(e.target.checked)} type="checkbox" /> Live
        </label>
        <span className="spacer" />
        <button
          className="small ghost"
          onClick={() =>
            void navigator.clipboard
              .writeText(lines.join('\n'))
              .then(() => toast({ title: 'Log copied', tone: 'ok' }))
              .catch(() => toast({ title: 'Copying is blocked in this browser', tone: 'danger' }))
          }
          type="button"
        >
          <Copy aria-hidden="true" size={14} /> Copy
        </button>
      </div>
      {logs.isError ? <ErrorMessage error={logs.error} /> : null}
      <LogView
        emptyText={logs.isPending ? 'Loading…' : 'The container has not logged anything.'}
        filter={filter}
        follow={filter === ''}
        label={`${name} log`}
        lines={lines}
      />
    </section>
  );
}

// -- settings ------------------------------------------------------------------------------------
type OverridesEditorProps = {
  fields: Field[];
  onReveal: () => void;
  overrides: Record<string, Record<string, unknown>>;
  repo: string;
  revealed: boolean;
  role: string;
};

const HIDDEN = '\u2039hidden\u203a';

function hasHidden(value: unknown): boolean {
  return JSON.stringify(value ?? null).includes(HIDDEN);
}

function OverridesEditor({ fields, onReveal, overrides, repo, revealed, role }: OverridesEditorProps): React.ReactNode {
  const update = useUpdateOverrides();
  const toast = useToast();
  const [key, setKey] = useState('');
  const [value, setValue] = useState('');
  const current = Object.entries(overrides).flatMap(([scope, values]) =>
    Object.entries(values).map(([name, current]) => ({ name, scope, value: current })),
  );
  const suggestions = fields.filter((f) => f.suffix !== null).map((f) => `${role}_role${f.suffix ?? ''}`);

  function submit(event: React.SubmitEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (key.trim() === '') return;
    update.mutate(
      { repo, role, values: { [key.trim()]: value } },
      {
        onSuccess: () => {
          toast({ body: 'Reinstall the app to apply it.', title: `${key.trim()} saved`, tone: 'ok' });
          setKey('');
          setValue('');
        },
      },
    );
  }

  return (
    <section aria-labelledby="overrides-title" className="card">
      <h2 id="overrides-title">Your overrides</h2>
      <p className="muted small">
        Saved to <code>inventories/host_vars/localhost.yml</code>. Role-wide keys look like{' '}
        <code>{role}_role_&lt;setting&gt;</code>, one instance’s like <code>{role}_&lt;setting&gt;</code>. They apply
        the next time the app is installed or reinstalled.
      </p>
      {current.some((entry) => hasHidden(entry.value)) || revealed ? (
        <div className={`note ${revealed ? 'warn' : ''} ${styles['secrets']}`}>
          <span>
            {revealed
              ? 'Secret values are visible.'
              : 'Passwords, tokens and keys are hidden. To change one, set the key again with the new value.'}
          </span>
          <button className="small" onClick={onReveal} type="button">
            {revealed ? 'Hide secrets' : 'Show secrets'}
          </button>
        </div>
      ) : null}
      {current.length === 0 ? (
        <p className="muted">No overrides; the defaults below apply.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Key</th>
              <th>Value</th>
              <th>Scope</th>
              <th>
                <span className="visually-hidden">Remove</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {current.map((entry) => (
              <tr key={entry.name}>
                <td>
                  <code>{entry.name}</code>
                </td>
                <td>
                  <code>{formatValue(entry.value)}</code>
                </td>
                <td className="muted">{entry.scope}</td>
                <td>
                  <button
                    className="small danger"
                    onClick={() => update.mutate({ repo, role, unset: [entry.name] })}
                    type="button"
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form className={`row ${styles['form']}`} onSubmit={submit}>
        <input
          aria-label="Override key"
          className={styles['key']}
          list="override-keys"
          onChange={(e) => setKey(e.target.value)}
          placeholder={`${role}_role_…`}
          value={key}
        />
        <datalist id="override-keys">
          {suggestions.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        <input
          aria-label="Override value"
          onChange={(e) => setValue(e.target.value)}
          placeholder="value"
          value={value}
        />
        <button className="primary" disabled={update.isPending} type="submit">
          Set
        </button>
      </form>
      {update.isError ? <ErrorMessage error={update.error} /> : null}
    </section>
  );
}

function DefaultsTable({ fields }: { fields: Field[] }): React.ReactNode {
  const [showHidden, setShowHidden] = useState(false);
  const [needle, setNeedle] = useState('');
  const shown = fields
    .filter((f) => showHidden || !f.hidden)
    .filter((f) => `${f.name} ${f.help}`.toLowerCase().includes(needle.toLowerCase()));
  return (
    <section className="card">
      <div className="row">
        <h2 className={styles['flush']}>Defaults</h2>
        <span className="spacer" />
        <input
          aria-label="Filter settings"
          onChange={(e) => setNeedle(e.target.value)}
          placeholder="Filter settings"
          type="search"
          value={needle}
        />
        <label className="row small muted">
          <input checked={showHidden} onChange={(e) => setShowHidden(e.target.checked)} type="checkbox" /> Show internal
        </label>
      </div>
      {shown.length === 0 ? (
        <p className="muted">{fields.length === 0 ? 'No defaults file for this role.' : 'No setting matches.'}</p>
      ) : (
        <table className={styles['defaults']}>
          <thead>
            <tr>
              <th>Setting</th>
              <th>Default</th>
              <th>Type</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((field) => (
              <tr key={field.name}>
                <td>
                  <code>{field.name}</code>
                  <div className="muted small">{field.section}</div>
                  {field.help !== '' ? <div className={`muted ${styles['help']}`}>{field.help}</div> : null}
                </td>
                <td>
                  <code>{defaultSource(field)}</code>
                </td>
                <td className="muted">
                  {field.type}
                  {field.hidden ? ` (${field.hidden_reason ?? 'internal'})` : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// -- details -------------------------------------------------------------------------------------
function DetailsTab({ detail }: { detail: AppDetail }): React.ReactNode {
  const { app, facts } = detail;
  return (
    <div className="stack">
      <section className="card">
        <h2>Role</h2>
        <table>
          <tbody>
            <tr>
              <th>Repository</th>
              <td>{app.repo}</td>
            </tr>
            <tr>
              <th>Role</th>
              <td>
                <code>{app.role}</code>
              </td>
            </tr>
            <tr>
              <th>Install tag</th>
              <td>
                <code>{app.sb_tag ?? app.install_tag ?? app.role}</code>
              </td>
            </tr>
            <tr>
              <th>Categories</th>
              <td>{app.categories.join(', ') || '—'}</td>
            </tr>
          </tbody>
        </table>
      </section>
      {Object.entries(facts).map(([section, values]) => (
        <section className="card" key={section}>
          <h2>Facts: {section}</h2>
          <table>
            <tbody>
              {Object.entries(values).map(([k, v]) => (
                <tr key={k}>
                  <th>
                    <code>{k}</code>
                  </th>
                  <td>
                    <code>{v}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}

// -- page ------------------------------------------------------------------------------------------
type Tab = 'details' | 'logs' | 'overview' | 'settings';

export function AppPage(): React.ReactNode {
  const { repo = 'saltbox', role = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const [revealed, setRevealed] = useState(false);
  const detail = useAppDetail(repo, role, revealed);
  const jobs = useJobs();
  const jobActions = useJobActions();
  const containers = useContainerActions();
  if (detail.isPending) return <Loading what="app" />;
  if (detail.isError) return <ErrorMessage error={detail.error} prefix="App" />;
  const data = detail.data;
  const installed = data.installed;
  const app = asApp(data, installed);
  const busy = jobs.data?.busy ?? false;
  const url = data.urls[0];
  const main = data.containers[0];
  const tabs: [Tab, string][] = installed
    ? [
        ['overview', 'Overview'],
        ['logs', 'Logs'],
        ['settings', 'Settings'],
        ['details', 'Details'],
      ]
    : [
        ['overview', 'Overview'],
        ['settings', 'Settings'],
        ['details', 'Details'],
      ];
  const requested = (params.get('tab') ?? 'overview') as Tab;
  const tab = tabs.some(([t]) => t === requested) ? requested : 'overview';

  return (
    <div className="stack">
      <Link className={`small ${styles['back']}`} to={installed ? '/apps' : '/apps/discover'}>
        <ArrowLeft aria-hidden="true" size={14} /> Apps
      </Link>
      <header className={styles['header']}>
        <AppAvatar size="lg" title={data.app.title} url={url} />
        <div className={styles['headText']}>
          <h1 className={styles['flush']}>
            {data.app.title}
            {repo === 'sandbox' ? <span className={styles['tag']}>Sandbox</span> : null}
          </h1>
          <div className="row small">
            {installed ? <StatusDot health={appHealth(app)} /> : <span className="muted">Not installed</span>}
            {url === undefined ? null : (
              <a href={url} rel="noreferrer" target="_blank">
                {hostOf(url)}
              </a>
            )}
            {data.app.docs_url === '' ? null : (
              <a className="row" href={data.app.docs_url} rel="noreferrer" target="_blank">
                <BookOpen aria-hidden="true" size={14} /> Docs
              </a>
            )}
          </div>
        </div>
        <div className={styles['actions']}>
          {url === undefined ? null : (
            <a className="button primary" href={url} rel="noreferrer" target="_blank">
              <ExternalLink aria-hidden="true" size={16} /> Open
            </a>
          )}
          {data.update_available ? (
            <button className="primary" disabled={busy} onClick={() => void jobActions.updateApp(app)} type="button">
              <ArrowUpCircle aria-hidden="true" size={16} /> Update
            </button>
          ) : null}
          {main === undefined ? null : main.status === 'running' ? (
            <button
              disabled={containers.pending}
              onClick={() => void containers.run(main.name, 'restart')}
              type="button"
            >
              <RotateCw aria-hidden="true" size={16} /> Restart
            </button>
          ) : (
            <button disabled={containers.pending} onClick={() => void containers.run(main.name, 'start')} type="button">
              <Play aria-hidden="true" size={16} /> Start
            </button>
          )}
          {installed ? (
            <button disabled={busy} onClick={() => void jobActions.install(app, true)} type="button">
              <Wrench aria-hidden="true" size={16} /> Reinstall
            </button>
          ) : (
            <button className="primary" disabled={busy} onClick={() => void jobActions.install(app)} type="button">
              <PackagePlus aria-hidden="true" size={16} /> Install
            </button>
          )}
        </div>
      </header>
      {data.app.summary !== '' && installed ? <p className="muted">{data.app.summary}</p> : null}
      {busy ? <p className="note">Another job is running; install and update buttons wait for it.</p> : null}

      <div className="tabs" role="tablist">
        {tabs.map(([value, label]) => (
          <button
            aria-selected={tab === value}
            className="tab"
            key={value}
            onClick={() => setParams(value === 'overview' ? {} : { tab: value }, { replace: true })}
            role="tab"
            type="button"
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'overview' ? <OverviewTab detail={data} installed={installed} /> : null}
      {tab === 'logs' ? <LogsTab containers={data.containers} /> : null}
      {tab === 'settings' ? (
        <div className="stack">
          <OverridesEditor
            fields={data.fields}
            onReveal={() => setRevealed((r) => !r)}
            overrides={data.overrides}
            repo={repo}
            revealed={revealed}
            role={role}
          />
          <DefaultsTable fields={data.fields} />
        </div>
      ) : null}
      {tab === 'details' ? <DetailsTab detail={data} /> : null}
    </div>
  );
}
