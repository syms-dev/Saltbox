import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { useJobs, useStartJob } from '../api/queries';
import type { JobRequest } from '../api/types';
import { ErrorMessage, Loading } from '../components/query-state';
import { StatusBadge } from '../components/status-badge';
import { formatDuration, formatWhen } from '../format';

export function parseTags(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((t) => t.trim())
    .filter((t) => t !== '');
}

export function JobsPage(): React.ReactNode {
  const jobs = useJobs();
  const start = useStartJob();
  const navigate = useNavigate();
  const [tags, setTags] = useState('');
  const [skipTags, setSkipTags] = useState('');
  const [verbose, setVerbose] = useState(false);

  function launch(request: JobRequest): void {
    start.mutate(request, { onSuccess: (job) => void navigate(`/jobs/${job.id}`) });
  }

  function submit(event: React.SubmitEvent<HTMLFormElement>): void {
    event.preventDefault();
    const tagList = parseTags(tags);
    if (tagList.length === 0) return;
    launch({ kind: 'install', skip_tags: parseTags(skipTags), tags: tagList, verbosity: verbose ? 1 : 0 });
  }

  if (jobs.isPending) return <Loading what="jobs" />;
  if (jobs.isError) return <ErrorMessage error={jobs.error} prefix="Jobs" />;
  const busy = jobs.data.busy;
  return (
    <div className="stack">
      <h1>Jobs</h1>
      <section className="card">
        <h2>Run</h2>
        <form className="stack" onSubmit={submit}>
          <div className="row">
            <label>
              Tags{' '}
              <input
                aria-label="Tags"
                onChange={(e) => setTags(e.target.value)}
                placeholder="sonarr,radarr"
                value={tags}
              />
            </label>
            <label>
              Skip tags{' '}
              <input
                aria-label="Skip tags"
                onChange={(e) => setSkipTags(e.target.value)}
                placeholder="optional"
                value={skipTags}
              />
            </label>
            <label>
              <input checked={verbose} onChange={(e) => setVerbose(e.target.checked)} type="checkbox" /> verbose
            </label>
            <button className="primary" disabled={busy || start.isPending} type="submit">
              sb install
            </button>
            <button disabled={busy || start.isPending} onClick={() => launch({ kind: 'update' })} type="button">
              sb update
            </button>
            <button disabled={busy || start.isPending} onClick={() => launch({ kind: 'validate' })} type="button">
              sb validate-config
            </button>
          </div>
          {busy ? <p className="muted">A job is running; wait for it to finish or cancel it.</p> : null}
          {start.isError ? <ErrorMessage error={start.error} /> : null}
          {jobs.data.lock !== null && jobs.data.current === null ? (
            <p className="muted">
              The runner lock is held by another process (the TUI or sbx). Jobs started there show up below when they
              finish.
            </p>
          ) : null}
        </form>
      </section>
      <section className="card">
        <h2>History</h2>
        {jobs.data.jobs.length === 0 ? (
          <p className="muted">No jobs yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Command</th>
                <th>Started</th>
                <th>Duration</th>
              </tr>
            </thead>
            <tbody>
              {jobs.data.jobs.map((job) => (
                <tr key={job.id}>
                  <td>
                    <StatusBadge status={job.status} />
                  </td>
                  <td>
                    <Link to={`/jobs/${job.id}`}>
                      <code>{job.command_line.replace(/^\S+\//, '')}</code>
                    </Link>
                  </td>
                  <td className="muted">{formatWhen(job.started_at)}</td>
                  <td className="muted">{formatDuration(job.started_at, job.finished_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
