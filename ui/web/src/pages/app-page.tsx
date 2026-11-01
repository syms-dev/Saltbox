import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { installRequest } from '../api/client';
import { useAppDetail, useJobs, useStartJob, useUpdateOverrides } from '../api/queries';
import type { Field } from '../api/types';
import { ErrorMessage, Loading } from '../components/query-state';
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

type OverridesEditorProps = {
  fields: Field[];
  overrides: Record<string, Record<string, unknown>>;
  repo: string;
  role: string;
};

function OverridesEditor({ fields, overrides, repo, role }: OverridesEditorProps): React.ReactNode {
  const update = useUpdateOverrides();
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
          setKey('');
          setValue('');
        },
      },
    );
  }

  return (
    <section className="card">
      <h2>Inventory overrides</h2>
      <p className="muted">
        Values written to <code>inventories/host_vars/localhost.yml</code>. Role-wide keys look like{' '}
        <code>{role}_role_&lt;setting&gt;</code>; instance keys like <code>{role}_&lt;setting&gt;</code>.
      </p>
      {current.length === 0 ? (
        <p className="muted">No overrides for this app; the role defaults apply.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Scope</th>
              <th>Key</th>
              <th>Value</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {current.map((entry) => (
              <tr key={entry.name}>
                <td>{entry.scope}</td>
                <td>
                  <code>{entry.name}</code>
                </td>
                <td>
                  <code>{formatValue(entry.value)}</code>
                </td>
                <td>
                  <button
                    className="danger"
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
          list="override-keys"
          onChange={(e) => setKey(e.target.value)}
          placeholder="key"
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
          placeholder="value (YAML scalar)"
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

export function AppPage(): React.ReactNode {
  const { repo = 'saltbox', role = '' } = useParams();
  const detail = useAppDetail(repo, role);
  const jobs = useJobs();
  const start = useStartJob();
  const navigate = useNavigate();
  const [showHidden, setShowHidden] = useState(false);
  if (detail.isPending) return <Loading what="app" />;
  if (detail.isError) return <ErrorMessage error={detail.error} prefix="App" />;
  const { app, facts, fields, instances, overrides } = detail.data;
  const tag = app.sb_tag ?? app.install_tag ?? app.role;
  const busy = jobs.data?.busy ?? false;

  function run(): void {
    start.mutate(installRequest([tag]), { onSuccess: (job) => void navigate(`/jobs/${job.id}`) });
  }

  const shownFields = fields.filter((f) => showHidden || !f.hidden);
  return (
    <div className="stack">
      <p>
        <Link to="/apps">← Apps</Link>
      </p>
      <div className="row">
        <h1 className={styles['title']}>{app.title}</h1>
        {app.docs_url !== '' ? (
          <a href={app.docs_url} rel="noreferrer" target="_blank">
            Docs
          </a>
        ) : null}
        {app.link !== '' ? (
          <a href={app.link} rel="noreferrer" target="_blank">
            Project
          </a>
        ) : null}
      </div>
      {app.summary !== '' ? <p className="muted">{app.summary}</p> : null}
      <section className="card">
        <div className="row">
          <button className="primary" disabled={busy || start.isPending} onClick={run} type="button">
            Run <code>sb install {tag}</code>
          </button>
          {busy ? <span className="muted">another job is running</span> : null}
          <span className="muted">
            Instances: {instances.join(', ')}
            {app.supports_instances ? '' : ' (single instance role)'}
          </span>
        </div>
        {start.isError ? <ErrorMessage error={start.error} /> : null}
      </section>
      <OverridesEditor fields={fields} overrides={overrides} repo={repo} role={role} />
      <section className="card">
        <div className="row">
          <h2 className={styles['title']}>Settings from the role defaults</h2>
          <label className="muted">
            <input checked={showHidden} onChange={(e) => setShowHidden(e.target.checked)} type="checkbox" /> show
            internal
          </label>
        </div>
        {shownFields.length === 0 ? (
          <p className="muted">No defaults file for this role in the checkout.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Section</th>
                <th>Setting</th>
                <th>Default</th>
                <th>Type</th>
              </tr>
            </thead>
            <tbody>
              {shownFields.map((field) => (
                <tr key={field.name}>
                  <td className="muted">{field.section}</td>
                  <td>
                    <code>{field.name}</code>
                    {field.help !== '' ? <div className={`muted ${styles['help']}`}>{field.help}</div> : null}
                  </td>
                  <td>
                    <code>{defaultSource(field)}</code>
                  </td>
                  <td className="muted">
                    {field.type}
                    {field.hidden ? ` (${field.hidden_reason ?? 'hidden'})` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {Object.keys(facts).length > 0 ? (
        <section className="card">
          <h2>Facts</h2>
          {Object.entries(facts).map(([section, values]) => (
            <div key={section}>
              <h3>{section}</h3>
              <table>
                <tbody>
                  {Object.entries(values).map(([k, v]) => (
                    <tr key={k}>
                      <td>
                        <code>{k}</code>
                      </td>
                      <td>
                        <code>{v}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </section>
      ) : null}
    </div>
  );
}
