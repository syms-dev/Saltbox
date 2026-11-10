import { useEffect, useState } from 'react';
import { NavLink, useParams } from 'react-router-dom';

import {
  useConfigFile,
  useConfigFiles,
  useInventory,
  useSaveConfig,
  useSaveInventory,
  useOverview,
  useValidateConfig,
} from '../api/queries';
import type { Issue } from '../api/types';
import { ErrorMessage, Loading } from '../components/query-state';
import styles from './config-page.module.css';

const INVENTORY = 'inventory';

function IssueList({ issues }: { issues: Issue[] }): React.ReactNode {
  if (issues.length === 0) return <p className={styles['ok']}>No validation issues.</p>;
  return (
    <ul className={styles['issues']}>
      {issues.map((issue) => (
        <li
          className={issue.level === 'error' ? styles['error'] : styles['warning']}
          key={`${issue.path}:${issue.message}`}
        >
          <code>{issue.path === '' ? 'file' : issue.path}</code> {issue.message}
        </li>
      ))}
    </ul>
  );
}

type EditorProps = {
  initial: string;
  isSaving: boolean;
  issues: Issue[];
  onSave: (text: string) => void;
  path: string;
  saveError: unknown;
  source?: string;
};

function Editor({ initial, isSaving, issues, onSave, path, saveError, source }: EditorProps): React.ReactNode {
  const [text, setText] = useState(initial);
  const [base, setBase] = useState(initial);
  // When the file reloads (after a save, or a background refetch), take the new text only if
  // nothing has been typed since the last load; never throw away an edit in progress.
  if (initial !== base) {
    setBase(initial);
    if (text === base) setText(initial);
  }
  const dirty = text !== base;
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (event: BeforeUnloadEvent): void => event.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  return (
    <div className="stack">
      <p className="muted">
        <code>{path}</code>
        {source === 'default' ? ' · not created yet, showing the default' : ''}
      </p>
      <textarea
        aria-label="File contents"
        className={`mono ${styles['editor']}`}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 's' && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            if (dirty && !isSaving) onSave(text);
          }
        }}
        spellCheck={false}
        value={text}
      />
      <div className="row">
        <button className="primary" disabled={!dirty || isSaving} onClick={() => onSave(text)} type="button">
          Save
        </button>
        <button disabled={!dirty} onClick={() => setText(base)} type="button">
          Revert
        </button>
        {dirty ? <span className="muted">unsaved changes</span> : null}
      </div>
      {saveError !== null && saveError !== undefined ? <ErrorMessage error={saveError} prefix="Save failed" /> : null}
      <IssueList issues={issues} />
    </div>
  );
}

function FileEditor({ name }: { name: string }): React.ReactNode {
  const file = useConfigFile(name);
  const save = useSaveConfig();
  if (file.isPending) return <Loading what={name} />;
  if (file.isError) return <ErrorMessage error={file.error} prefix={name} />;
  return (
    <Editor
      initial={file.data.text}
      isSaving={save.isPending}
      issues={save.data?.issues ?? file.data.issues}
      onSave={(text) => save.mutate({ name, text })}
      path={file.data.path}
      saveError={save.error}
      source={file.data.source}
    />
  );
}

function InventoryEditor(): React.ReactNode {
  const inventory = useInventory();
  const save = useSaveInventory();
  if (inventory.isPending) return <Loading what="inventory" />;
  if (inventory.isError) return <ErrorMessage error={inventory.error} prefix="Inventory" />;
  return (
    <Editor
      initial={inventory.data.text}
      isSaving={save.isPending}
      issues={save.data?.issues ?? inventory.data.issues}
      onSave={(text) => save.mutate(text)}
      path={inventory.data.path}
      saveError={save.error}
    />
  );
}

const DESCRIPTIONS: Record<string, string> = {
  accounts: 'Your user, password, domain and Cloudflare login',
  adv_settings: 'DNS records, Traefik, GPU and other advanced options',
  backup_config: 'Where and when backups run',
  hetzner_vlan: 'Hetzner vSwitch networking',
  inventory: 'Per-app overrides (the settings Apps → Settings writes)',
  providers: 'API keys for DNS and other providers',
  settings: 'Paths, downloads folder, rclone remotes, shell',
};

export function ConfigPage(): React.ReactNode {
  const { name = 'accounts' } = useParams();
  const files = useConfigFiles();
  const validate = useValidateConfig();
  const overview = useOverview();
  const issues = validate.data ?? overview.data?.config_issues ?? {};
  const errorsIn = (file: string): number => (issues[file] ?? []).filter((i) => i.level === 'error').length;
  const total = Object.keys(issues).reduce((sum, file) => sum + errorsIn(file), 0);
  const entries = [
    ...(files.data ?? []).map((file) => ({ exists: file.exists, filename: file.filename, name: file.name })),
    { exists: true, filename: 'inventories/host_vars/localhost.yml', name: INVENTORY },
  ];
  return (
    <div className="stack">
      <div className="row">
        <h1 className={styles['flush']}>Config</h1>
        <span className="spacer" />
        <span className={`small ${total > 0 ? styles['error'] : 'muted'}`}>
          {total === 0 ? 'No validation errors' : `${total} error${total === 1 ? '' : 's'} across all files`}
        </span>
        <button disabled={validate.isPending} onClick={() => validate.mutate()} type="button">
          Validate all
        </button>
      </div>
      <p className="muted">
        The files <code>sb</code> reads, checked against the same schema as <code>sb validate-config</code>. Comments
        are kept when you save. Changes take effect the next time the affected apps are installed.
      </p>
      <div className={styles['layout']}>
        <nav aria-label="Config files" className={styles['files']}>
          {entries.map((file) => (
            <NavLink className={styles['file'] ?? ''} key={file.name} to={`/config/${file.name}`}>
              <span className={styles['fileName']}>
                {file.filename}
                {errorsIn(file.name) > 0 ? <span className={styles['errorCount']}>{errorsIn(file.name)}</span> : null}
              </span>
              <span className={styles['fileHelp']}>
                {file.exists ? (DESCRIPTIONS[file.name] ?? '') : 'Not created yet'}
              </span>
            </NavLink>
          ))}
        </nav>
        <section className="card">{name === INVENTORY ? <InventoryEditor /> : <FileEditor name={name} />}</section>
      </div>
    </div>
  );
}
