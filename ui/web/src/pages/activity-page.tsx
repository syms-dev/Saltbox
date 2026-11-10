import { ChevronRight, Terminal } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { useApps, useJobs, useStartJob } from '../api/queries';
import type { Job, JobRequest } from '../api/types';
import { useToast } from '../components/feedback';
import { ErrorMessage, Loading } from '../components/query-state';
import { jobTitle } from '../components/shell';
import { StatusDot } from '../components/status-dot';
import { formatDuration, formatRelative } from '../format';
import type { Health } from '../lib/status';
import styles from './activity-page.module.css';

export function parseTags(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((t) => t.trim())
    .filter((t) => t !== '');
}

export function jobHealth(job: Pick<Job, 'status'>): Health {
  switch (job.status) {
    case 'succeeded':
      return { label: 'Succeeded', tone: 'ok' };
    case 'failed':
      return { label: 'Failed', tone: 'danger' };
    case 'running':
    case 'pending':
      return { label: 'Running', tone: 'warn' };
    default:
      return { label: 'Stopped', tone: 'muted' };
  }
}

function RunPanel({ busy }: { busy: boolean }): React.ReactNode {
  const start = useStartJob();
  const apps = useApps();
  const navigate = useNavigate();
  const toast = useToast();
  const [tags, setTags] = useState('');
  const [skipTags, setSkipTags] = useState('');
  const [verbose, setVerbose] = useState(false);
  const suggestions = Array.from(new Set((apps.data ?? []).map((app) => app.sb_tag ?? app.install_tag ?? app.role)));

  function launch(request: JobRequest): void {
    start.mutate(request, {
      onError: (error) => toast({ body: error.message, title: 'Could not start the job', tone: 'danger' }),
      onSuccess: (job) => void navigate(`/activity/${job.id}`),
    });
  }

  function submit(event: React.SubmitEvent<HTMLFormElement>): void {
    event.preventDefault();
    const tagList = parseTags(tags);
    if (tagList.length === 0) return;
    launch({ kind: 'install', skip_tags: parseTags(skipTags), tags: tagList, verbosity: verbose ? 1 : 0 });
  }

  return (
    <details className={`card ${styles['run']}`}>
      <summary>
        <Terminal aria-hidden="true" size={16} /> Run an sb command
      </summary>
      <form className="stack-sm" onSubmit={submit}>
        <p className="muted small">
          The same as <code>sb install &lt;tags&gt;</code> on the server. Separate tags with commas or spaces.
        </p>
        <div className="row">
          <input
            aria-label="Tags"
            className={styles['tags']}
            list="sb-tags"
            onChange={(e) => setTags(e.target.value)}
            placeholder="sonarr,radarr"
            value={tags}
          />
          <datalist id="sb-tags">
            {suggestions.map((tag) => (
              <option key={tag} value={tag} />
            ))}
          </datalist>
          <input
            aria-label="Skip tags"
            onChange={(e) => setSkipTags(e.target.value)}
            placeholder="skip tags (optional)"
            value={skipTags}
          />
          <label className="row small">
            <input checked={verbose} onChange={(e) => setVerbose(e.target.checked)} type="checkbox" /> Verbose
          </label>
        </div>
        <div className="row">
          <button className="primary" disabled={busy || start.isPending} type="submit">
            sb install
          </button>
          <button disabled={busy || start.isPending} onClick={() => launch({ kind: 'update' })} type="button">
            sb update
          </button>
          <button disabled={busy || start.isPending} onClick={() => launch({ kind: 'validate' })} type="button">
            sb validate-config
          </button>
          {busy ? <span className="muted small">A job is running; wait for it or cancel it.</span> : null}
        </div>
      </form>
    </details>
  );
}

export function ActivityPage(): React.ReactNode {
  const jobs = useJobs();
  const [failedOnly, setFailedOnly] = useState(false);
  if (jobs.isPending) return <Loading what="activity" />;
  if (jobs.isError) return <ErrorMessage error={jobs.error} prefix="Activity" />;
  const busy = jobs.data.busy;
  const failed = jobs.data.jobs.filter((job) => job.status === 'failed');
  const shown = failedOnly ? failed : jobs.data.jobs;
  return (
    <div className="stack">
      <h1>Activity</h1>
      <RunPanel busy={busy} />
      {jobs.data.lock !== null && jobs.data.current === null ? (
        <p className="note">
          A job started from the terminal (the installer or sbx) is running. It shows up here when it finishes.
        </p>
      ) : null}
      <div className="chips">
        <button aria-pressed={!failedOnly} className="chip" onClick={() => setFailedOnly(false)} type="button">
          All <span className="count">{jobs.data.jobs.length}</span>
        </button>
        <button aria-pressed={failedOnly} className="chip" onClick={() => setFailedOnly(true)} type="button">
          Failed <span className="count">{failed.length}</span>
        </button>
      </div>
      {shown.length === 0 ? (
        <div className="card empty">
          <p>{failedOnly ? 'No failed jobs.' : 'Nothing has run from here yet.'}</p>
        </div>
      ) : (
        <ul aria-label="Jobs" className={`card ${styles['list']}`}>
          {shown.map((job) => (
            <li key={job.id}>
              <Link className={styles['job']} to={`/activity/${job.id}`}>
                <StatusDot health={jobHealth(job)} showLabel={false} />
                <span className={styles['jobMain']}>
                  <code className={styles['command']}>{jobTitle(job)}</code>
                  <span className="muted small">
                    {jobHealth(job).label} · {formatRelative(job.started_at)} ·{' '}
                    {formatDuration(job.started_at, job.finished_at)}
                  </span>
                </span>
                <ChevronRight aria-hidden="true" className="muted" size={16} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
