import { useEffect, useState } from 'react';
import { NavLink, useParams } from 'react-router-dom';

import {
  useConfigFile,
  useConfigFiles,
  useInventory,
  useSaveConfig,
  useSaveInventory,
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
  useEffect(() => setText(initial), [initial]);
  const dirty = text !== initial;
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
        spellCheck={false}
        value={text}
      />
      <div className="row">
        <button className="primary" disabled={!dirty || isSaving} onClick={() => onSave(text)} type="button">
          Save
        </button>
        <button disabled={!dirty} onClick={() => setText(initial)} type="button">
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

export function ConfigPage(): React.ReactNode {
  const { name = 'accounts' } = useParams();
  const files = useConfigFiles();
  const validate = useValidateConfig();
  return (
    <div className="stack">
      <div className="row">
        <h1 style={{ margin: 0 }}>Config</h1>
        <button disabled={validate.isPending} onClick={() => validate.mutate()} type="button">
          Validate all
        </button>
        {validate.data !== undefined ? (
          <span className="muted">
            {
              Object.values(validate.data)
                .flat()
                .filter((i) => i.level === 'error').length
            }{' '}
            errors across all files
          </span>
        ) : null}
      </div>
      <p className="muted">
        The same files <code>sb validate-config</code> checks. Comments are kept; saving validates against the schema.
      </p>
      <div className={styles['layout']}>
        <nav aria-label="Config files" className={styles['files']}>
          {files.data?.map((file) => (
            <NavLink className={styles['file'] ?? ''} key={file.name} to={`/config/${file.name}`}>
              {file.filename}
              {file.exists ? '' : <span className="muted"> (missing)</span>}
            </NavLink>
          ))}
          <NavLink className={styles['file'] ?? ''} to={`/config/${INVENTORY}`}>
            inventories/host_vars/localhost.yml
          </NavLink>
        </nav>
        <section className="card">{name === INVENTORY ? <InventoryEditor /> : <FileEditor name={name} />}</section>
      </div>
    </div>
  );
}
