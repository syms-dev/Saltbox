import { ArrowLeft, CircleAlert, CircleCheck, CircleHelp, CircleStop, Copy, Megaphone, RotateCw } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { useAnswerJob, useCancelJob, useJob, useJobs, useStartJob } from '../api/queries';
import type { Announcement, JobQuestion } from '../api/types';
import { useConfirm, useToast } from '../components/feedback';
import { LogView } from '../components/log-view';
import { ErrorMessage, Loading } from '../components/query-state';
import { jobTitle } from '../components/shell';
import { StatusDot } from '../components/status-dot';
import { useJobStream } from '../components/use-job-stream';
import { formatDuration, formatWhen } from '../format';
import { findFailure } from '../lib/ansible';
import { jobHealth } from './activity-page';
import styles from './job-page.module.css';

/** "ok=12 changed=1 failed=0" from the recap, summed over hosts. */
export function recap(log: string): Record<string, number> | null {
  const lines = log.split('\n').filter((line) => /\bok=\d+/.test(line) && /\bfailed=\d+/.test(line));
  if (lines.length === 0) return null;
  const totals: Record<string, number> = {};
  for (const line of lines) {
    for (const match of line.matchAll(/(\w+)=(\d+)/g)) {
      const [, key = '', value = '0'] = match;
      totals[key] = (totals[key] ?? 0) + Number(value);
    }
  }
  return totals;
}

/** The yes/no question `sb update` asks at its terminal, asked here instead. */
export function MigrationQuestion({ id, question }: { id: string; question: JobQuestion }): React.ReactNode {
  const answer = useAnswerJob();
  const toast = useToast();

  function reply(yes: boolean): void {
    answer.mutate(
      { answer: yes, id },
      { onError: (error) => toast({ body: error.message, title: 'Could not send the answer', tone: 'danger' }) },
    );
  }

  return (
    <section aria-labelledby="question-title" className={`note warn ${styles['outcome']}`} role="alert">
      <CircleHelp aria-hidden="true" className={styles['icon']} size={20} />
      <div className={`stack-sm ${styles['question']}`}>
        <strong id="question-title">Saltbox is waiting for your answer: run the migrations for this update?</strong>
        {question.migrations.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th scope="col">Repository</th>
                <th scope="col">Tag</th>
                <th scope="col">Announced</th>
              </tr>
            </thead>
            <tbody>
              {question.migrations.map((migration) => (
                <tr key={`${migration.repo}/${migration.tag}`}>
                  <td>{migration.repo}</td>
                  <td>
                    <code>{migration.tag}</code>
                  </td>
                  <td>{migration.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <pre className={styles['message']}>{question.text}</pre>
        )}
        <p className="small">
          These are Saltbox playbook tags that move an existing install over to what this update changed; the
          announcements below say why. <code>sb update</code> asks once: if you skip them, it will not offer them again
          and you would run the tags yourself with <code>sb install</code>. The update waits here until you answer or
          cancel it.
        </p>
        <div className="row">
          <button className="primary" disabled={answer.isPending} onClick={() => reply(true)} type="button">
            Run the migrations
          </button>
          <button disabled={answer.isPending} onClick={() => reply(false)} type="button">
            Skip them
          </button>
        </div>
      </div>
    </section>
  );
}

/** What `sb update` shows in its full-screen viewer: the announcements this update brought. */
export function Announcements({ items }: { items: Announcement[] }): React.ReactNode {
  return (
    <section aria-labelledby="announcements-title" className="card stack-sm">
      <h2 className={styles['flush']} id="announcements-title">
        <Megaphone aria-hidden="true" size={18} /> Announcements from this update
      </h2>
      {items.map((item) => (
        <article className={styles['announcement']} key={`${item.repo}/${item.date}/${item.title}`}>
          <h3 className={styles['flush']}>{item.title}</h3>
          <p className="small muted">
            {item.repo} · {item.date}
            {item.migration === null ? null : (
              <>
                {' '}
                · migration tag <code>{item.migration}</code>
              </>
            )}
          </p>
          <p className={styles['announcementText']}>{item.message}</p>
        </article>
      ))}
    </section>
  );
}

export function JobPage(): React.ReactNode {
  const { id = '' } = useParams();
  // Keyed by job, so moving from one job's page to another starts with an empty log.
  return <JobView id={id} key={id} />;
}

function JobView({ id }: { id: string }): React.ReactNode {
  const job = useJob(id);
  const stream = useJobStream(id);
  const cancel = useCancelJob();
  const start = useStartJob();
  const jobs = useJobs();
  const confirm = useConfirm();
  const toast = useToast();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');
  const [jump, setJump] = useState<number | null>(null);
  const lines = useMemo(() => (stream.text === '' ? [] : stream.text.replace(/\n$/, '').split('\n')), [stream.text]);
  const failure = useMemo(() => findFailure(stream.text), [stream.text]);
  const totals = useMemo(() => recap(stream.text), [stream.text]);

  if (job.isPending) return <Loading what="job" />;
  if (job.isError) return <ErrorMessage error={job.error} prefix="Job" />;
  const record = stream.done ?? job.data;
  const active = record.status === 'running' || record.status === 'pending';
  const health = jobHealth(record);
  // The question and the announcements arrive on the polled record while the job runs.
  const question = active ? (job.data.question ?? null) : null;
  const announcements = record.announcements ?? job.data.announcements ?? [];

  async function stop(): Promise<void> {
    const ok = await confirm({
      body: <p>Ansible stops where it is. Run the same command again later to finish what it was doing.</p>,
      confirmLabel: 'Cancel the job',
      title: 'Cancel this job?',
      tone: 'danger',
    });
    if (ok) cancel.mutate(id);
  }

  function again(): void {
    start.mutate(
      {
        kind: record.kind === 'update' ? 'update' : record.kind === 'validate' ? 'validate' : 'install',
        tags: record.tags,
      },
      {
        onError: (error) => toast({ body: error.message, title: 'Could not start the job', tone: 'danger' }),
        onSuccess: (next) => void navigate(`/activity/${next.id}`),
      },
    );
  }

  return (
    <div className="stack">
      <Link className={`small ${styles['back']}`} to="/activity">
        <ArrowLeft aria-hidden="true" size={14} /> Activity
      </Link>
      <header className={styles['header']}>
        <div className={styles['title']}>
          <h1 className={styles['command']}>{jobTitle(record)}</h1>
          <div className="row small muted">
            <StatusDot health={health} />
            <span>started {formatWhen(record.started_at)}</span>
            <span>· {formatDuration(record.started_at, record.finished_at)}</span>
            {record.returncode !== null ? <span>· exit code {record.returncode}</span> : null}
            {active && !stream.connected ? <span>· reconnecting to the log…</span> : null}
          </div>
        </div>
        <div className="row">
          {active ? (
            <button className="danger" disabled={cancel.isPending} onClick={() => void stop()} type="button">
              <CircleStop aria-hidden="true" size={15} /> Cancel
            </button>
          ) : (
            <button disabled={start.isPending || jobs.data?.busy === true} onClick={again} type="button">
              <RotateCw aria-hidden="true" size={15} /> Run again
            </button>
          )}
        </div>
      </header>
      {cancel.isError ? <ErrorMessage error={cancel.error} /> : null}

      {question === null ? null : <MigrationQuestion id={id} question={question} />}
      {record.status === 'failed' ? (
        <section className={`note danger ${styles['outcome']}`} role="alert">
          <CircleAlert aria-hidden="true" size={20} />
          <div>
            <strong>The job failed{failure?.task == null ? '' : ` at “${failure.task}”`}.</strong>
            <p className={styles['message']}>{failure?.message ?? 'Look for the first error in the log below.'}</p>
            {failure === null ? null : (
              <button className="small" onClick={() => setJump(failure.line)} type="button">
                Show it in the log
              </button>
            )}
          </div>
        </section>
      ) : null}
      {record.status === 'succeeded' ? (
        <section className={`note ok ${styles['outcome']}`}>
          <CircleCheck aria-hidden="true" size={20} />
          <div>
            <strong>Finished without errors.</strong>
            {totals === null ? null : (
              <p className={styles['message']}>
                {totals['ok'] ?? 0} tasks ok, {totals['changed'] ?? 0} changed, {totals['skipped'] ?? 0} skipped.
              </p>
            )}
          </div>
        </section>
      ) : null}

      {announcements.length > 0 ? <Announcements items={announcements} /> : null}

      <section className="card stack-sm">
        <div className="row">
          <h2 className={styles['flush']}>Log</h2>
          <span className="spacer" />
          <input
            aria-label="Filter log lines"
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter lines"
            type="search"
            value={filter}
          />
          <button
            className="small ghost"
            onClick={() =>
              void navigator.clipboard
                .writeText(stream.text)
                .then(() => toast({ title: 'Log copied', tone: 'ok' }))
                .catch(() => toast({ title: 'Copying is blocked in this browser', tone: 'danger' }))
            }
            type="button"
          >
            <Copy aria-hidden="true" size={14} /> Copy
          </button>
        </div>
        <LogView
          emptyText="Waiting for output…"
          filter={filter}
          follow={active && filter === '' && jump === null}
          highlightLine={jump ?? (record.status === 'failed' ? (failure?.line ?? null) : null)}
          label="Job log"
          lines={lines}
        />
      </section>
    </div>
  );
}
