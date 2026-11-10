import { useNavigate } from 'react-router-dom';

import { useCheckUpdates, useJobs, useUpdateSaltbox, useUpdates } from '../api/queries';
import type { RepoStatus } from '../api/types';
import { UpdateBadge } from './app-links';
import { ErrorMessage } from './query-state';
import styles from './saltbox-updates.module.css';

/** "saltbox: main at abc1234", with the remote commit when it differs. */
export function repoLine(repo: RepoStatus): string {
  if (repo.branch === '') return `${repo.name} at ${repo.commit}`;
  const remote = repo.status === 'update' && repo.remote_commit !== '' ? ` → ${repo.remote_commit}` : '';
  return `${repo.name}: ${repo.branch} at ${repo.commit}${remote}`;
}

/** Whether the Saltbox checkouts are behind their branches, and a button that runs `sb update`. */
export function SaltboxUpdates(): React.ReactNode {
  const updates = useUpdates();
  const jobs = useJobs();
  const check = useCheckUpdates();
  const update = useUpdateSaltbox();
  const navigate = useNavigate();
  const repos = updates.data?.repos ?? [];
  const behind = repos.filter((repo) => repo.status === 'update');
  const busy = (jobs.data?.busy ?? false) || update.isPending;

  function run(): void {
    const names = behind.length > 0 ? behind.map((repo) => repo.name).join(', ') : 'the Saltbox checkouts';
    const message = `Run sb update? It resets ${names} to the latest commit on their branches and refreshes the settings files. Apps keep running.`;
    if (!window.confirm(message)) return;
    update.mutate(undefined, { onSuccess: (job) => void navigate(`/jobs/${job.id}`) });
  }

  return (
    <section className="card">
      <div className="row">
        <h3 className={styles['title']}>Saltbox</h3>
        <button
          disabled={check.isPending || updates.data?.running === true}
          onClick={() => check.mutate()}
          type="button"
        >
          Check now
        </button>
        <button className={behind.length > 0 ? 'primary' : ''} disabled={busy} onClick={run} type="button">
          Run <code>sb update</code>
        </button>
      </div>
      {repos.length === 0 ? (
        <p className="muted">{updates.data?.running === true ? 'Checking…' : 'Not checked yet.'}</p>
      ) : (
        <ul className={styles['repos']}>
          {repos.map((repo) => (
            <li key={repo.path}>
              <UpdateBadge detail={repo.detail} state={repo.status} /> <code>{repoLine(repo)}</code>
              {repo.status === 'unknown' && repo.detail !== '' ? (
                <div className={`muted ${styles['detail']}`}>{repo.detail}</div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {update.isError ? <ErrorMessage error={update.error} /> : null}
    </section>
  );
}
