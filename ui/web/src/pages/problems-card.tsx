import { RefreshCw, Stethoscope } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';

import { useProblems, useRefreshProblems } from '../api/queries';
import type { LogGroup, LogProblems } from '../api/types';
import { formatRelative } from '../format';
import type { Attention } from './home-attention';
import styles from './problems-card.module.css';

type Finding = { app: string; group: LogGroup; logs: string; name: string };

/** Every recurring error, with the app it belongs to and the way to that app's log. */
export function findings(problems: LogProblems | undefined): Finding[] {
  return (problems?.containers ?? []).flatMap((container) =>
    container.groups.map((group) => ({
      app: container.app?.title ?? container.name,
      group,
      logs: container.app === null ? '/apps' : `/apps/${container.app.repo}/${container.app.role}?tab=logs`,
      name: container.name,
    })),
  );
}

function times(count: number): string {
  return count === 1 ? 'once' : `${count} times`;
}

/** Known errors that mean something is not working belong on Home, with the way to the fix. */
export function problemAttention(problems: LogProblems | undefined): Attention[] {
  return findings(problems)
    .filter((finding) => finding.group.rule?.severity === 'problem')
    .map((finding) => ({
      actions: [{ kind: 'link' as const, label: 'How to fix it', to: '/system#problems' }],
      detail: `${finding.app} logged it ${times(finding.group.count)} in the last day.`,
      id: `log:${finding.name}:${finding.group.rule?.id ?? ''}`,
      title: finding.group.rule?.title ?? finding.app,
      tone: 'warn' as const,
    }));
}

/** A step with `commands` set in backticks shown as code. */
function Step({ text }: { text: string }): React.ReactNode {
  return (
    <li>
      {text.split('`').map((part, index) =>
        // Parts between a pair of backticks are the odd ones; the sentence is fixed, so its
        // position is a stable key.
        index % 2 === 1 ? <code key={index}>{part}</code> : <span key={index}>{part}</span>,
      )}
    </li>
  );
}

function Known({ finding }: { finding: Finding }): React.ReactNode {
  const { group } = finding;
  if (group.rule === null) return null;
  return (
    <article className={`${styles['finding']} ${group.rule.severity === 'problem' ? styles['problem'] : ''}`}>
      <h3 className={styles['flush']}>{group.rule.title}</h3>
      <p className="small muted">
        {finding.app} · logged {times(group.count)}
        {group.last_seen === '' ? '' : `, last ${formatRelative(group.last_seen)}`}
        {group.rule.severity === 'notice' ? ' · harmless' : ''}
      </p>
      <p>{group.rule.meaning}</p>
      <ol className={styles['steps']}>
        {group.rule.fix.map((step) => (
          <Step key={step} text={step} />
        ))}
      </ol>
      <p className={styles['line']}>{group.message}</p>
      <Link className="small" to={finding.logs}>
        Open {finding.app}’s log
      </Link>
    </article>
  );
}

/** Errors that keep coming back in the apps' logs; the known ones say what to do. */
export function ProblemsCard(): React.ReactNode {
  const problems = useProblems();
  const refresh = useRefreshProblems();
  const location = useLocation();
  const section = useRef<HTMLElement>(null);
  const loaded = problems.data !== undefined;
  useEffect(() => {
    // Home links here by name; bring the card into view once it has something to show.
    if (loaded && location.hash === '#problems') section.current?.scrollIntoView({ block: 'start' });
  }, [loaded, location.hash]);

  const all = findings(problems.data);
  const known = all.filter((finding) => finding.group.rule !== null);
  const unknown = all.filter((finding) => finding.group.rule === null);
  const reading = problems.isPending || refresh.isPending;
  return (
    <section aria-labelledby="problems-title" className="card stack-sm" id="problems" ref={section}>
      <div className="row">
        <h2 className={styles['title']} id="problems-title">
          <Stethoscope aria-hidden="true" size={18} /> Problems in app logs
        </h2>
        <span className="spacer" />
        <button className="small ghost" disabled={reading} onClick={() => refresh.mutate()} type="button">
          <RefreshCw aria-hidden="true" className={reading ? 'spin' : ''} size={14} /> Check again
        </button>
      </div>
      {problems.data === undefined ? (
        <p className="muted small">
          {problems.isError
            ? `Could not read the logs: ${problems.error.message}`
            : 'Reading the last day of every app’s log…'}
        </p>
      ) : !problems.data.available ? (
        <p className="muted small">Docker is not answering, so the logs cannot be read.</p>
      ) : all.length === 0 ? (
        <p className="muted small">
          No error keeps coming back in the last day of {problems.data.scanned} containers’ logs. Checked{' '}
          {formatRelative(problems.data.checked_at)}.
        </p>
      ) : (
        <>
          <p className="muted small">
            From the last day of {problems.data.scanned} containers’ logs, checked{' '}
            {formatRelative(problems.data.checked_at)}. Nothing is changed for you: each one says what it means and what
            to do.
          </p>
          {known.map((finding) => (
            <Known finding={finding} key={`${finding.name}:${finding.group.rule?.id ?? ''}`} />
          ))}
          {unknown.length === 0 ? null : (
            <details className={styles['others']} open={known.length === 0}>
              <summary>
                {unknown.length === 1
                  ? '1 other error that keeps repeating'
                  : `${unknown.length} other errors that keep repeating`}
              </summary>
              <ul className={styles['list']}>
                {unknown.map((finding) => (
                  <li key={`${finding.name}:${finding.group.message}`}>
                    <span className="small muted">
                      <Link to={finding.logs}>{finding.app}</Link> · {times(finding.group.count)}
                      {finding.group.last_seen === '' ? '' : `, last ${formatRelative(finding.group.last_seen)}`}
                    </span>
                    <span className={styles['line']}>{finding.group.message}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}
