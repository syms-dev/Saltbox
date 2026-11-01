import { Link, useParams } from 'react-router-dom';

import { useCancelJob, useJob } from '../api/queries';
import { JobLog } from '../components/job-log';
import { ErrorMessage, Loading } from '../components/query-state';
import { StatusBadge } from '../components/status-badge';
import { useJobStream } from '../components/use-job-stream';
import { formatDuration, formatWhen } from '../format';

export function JobPage(): React.ReactNode {
  const { id = '' } = useParams();
  const job = useJob(id);
  const stream = useJobStream(id);
  const cancel = useCancelJob();
  if (job.isPending) return <Loading what="job" />;
  if (job.isError) return <ErrorMessage error={job.error} prefix="Job" />;
  const record = stream.done ?? job.data;
  const active = record.status === 'running' || record.status === 'pending';
  return (
    <div className="stack">
      <p>
        <Link to="/jobs">← Jobs</Link>
      </p>
      <div className="row">
        <h1 style={{ margin: 0 }}>
          <code>{record.command_line.replace(/^\S+\//, '')}</code>
        </h1>
        <StatusBadge status={record.status} />
        {active ? (
          <button className="danger" disabled={cancel.isPending} onClick={() => cancel.mutate(id)} type="button">
            Cancel
          </button>
        ) : null}
      </div>
      <p className="muted">
        started {formatWhen(record.started_at)}
        {record.finished_at !== null ? `, finished ${formatWhen(record.finished_at)}` : ''},{' '}
        {formatDuration(record.started_at, record.finished_at)}
        {record.returncode !== null ? `, exit code ${record.returncode}` : ''}
        {active && !stream.connected ? ' · reconnecting to the log stream' : ''}
      </p>
      {cancel.isError ? <ErrorMessage error={cancel.error} /> : null}
      {record.status === 'failed' ? (
        <p role="alert" style={{ color: 'var(--color-danger)' }}>
          The job failed. Look for the first <code>fatal:</code> line in the log, and the recap at the end.
        </p>
      ) : null}
      <JobLog follow={active} text={stream.text} />
    </div>
  );
}
