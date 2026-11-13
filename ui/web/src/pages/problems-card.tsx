import { ChevronRight, RefreshCw, Stethoscope, Wrench } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';

import { useDismiss, useFixProblem, useProblems, useRefreshProblems } from '../api/queries';
import type { LogGroup, LogProblems } from '../api/types';
import { useToast } from '../components/feedback';
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

/** Known errors that mean something is not working belong on Home, until they are dismissed. */
export function problemAttention(problems: LogProblems | undefined): Attention[] {
  return findings(problems)
    .filter((finding) => finding.group.rule?.severity === 'problem' && finding.group.dismissed !== true)
    .map((finding) => ({
      actions: [{ kind: 'link' as const, label: 'How to fix it', to: '/system#problems' }],
      detail: `${finding.app} logged it ${times(finding.group.count)} in the last day.`,
      id: finding.group.key,
      title: finding.group.rule?.title ?? finding.app,
      tone: 'warn' as const,
    }));
}

type Kind = 'minor' | 'notice' | 'problem' | 'unexplained';

const KINDS: Record<Kind, string> = {
  minor: 'Minor',
  notice: 'Harmless',
  problem: 'Needs fixing',
  unexplained: 'Unexplained',
};

function kindOf(group: LogGroup): Kind {
  return group.rule?.severity ?? 'unexplained';
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

/** One issue: what it is, whose it is, what to do, and the buttons that act on it. */
function Issue({ finding }: { finding: Finding }): React.ReactNode {
  const { group } = finding;
  const kind = kindOf(group);
  const dismiss = useDismiss();
  const fix = useFixProblem();
  const toast = useToast();
  const title = group.rule?.title ?? `${finding.app} keeps logging the same error`;
  const subjects = group.subjects ?? [];
  const action = group.action ?? null;
  return (
    <article aria-label={title} className={`${styles['issue']} ${styles[kind]}`}>
      <header className={styles['head']}>
        <span className={`${styles['badge']} ${styles[`${kind}Badge`]}`}>{KINDS[kind]}</span>
        <span className="small muted">
          {finding.app} · logged {times(group.count)}
          {group.last_seen === '' ? '' : `, last ${formatRelative(group.last_seen)}`}
        </span>
      </header>
      <h3 className={styles['flush']}>{title}</h3>
      {group.rule === null ? (
        <p>
          There is no explanation on file for this one. The line below is its latest occurrence; the rest of{' '}
          {finding.app}’s log around it usually says what it was doing.
        </p>
      ) : (
        <>
          <p>{group.rule.meaning}</p>
          <div>
            <h4 className={styles['label']}>What to do</h4>
            <ol className={styles['steps']}>
              {group.rule.fix.map((step) => (
                <Step key={step} text={step} />
              ))}
            </ol>
          </div>
        </>
      )}
      {subjects.length === 0 ? null : (
        <div>
          <h4 className={styles['label']}>
            {subjects.length + (group.more_subjects ?? 0) === 1 ? 'The file' : 'The files'}
          </h4>
          <ul className={styles['files']}>
            {subjects.map((subject) => (
              <li key={subject}>{subject}</li>
            ))}
            {(group.more_subjects ?? 0) > 0 ? <li>and {group.more_subjects} more</li> : null}
          </ul>
        </div>
      )}
      <div>
        <h4 className={styles['label']}>Latest line</h4>
        <p className={styles['line']}>{group.message}</p>
      </div>
      {action === null ? null : <p className="small muted">{action.detail}</p>}
      <footer className={styles['actions']}>
        {action === null ? null : (
          <button
            className="small primary"
            disabled={fix.isPending}
            onClick={() =>
              fix.mutate(group.key, {
                onError: (error) => toast({ body: error.message, title: 'The fix did not work', tone: 'danger' }),
                onSuccess: (result) =>
                  toast({ body: `Created ${result.created.join(', ')}.`, title: 'Fixed', tone: 'ok' }),
              })
            }
            type="button"
          >
            <Wrench aria-hidden="true" size={14} /> {action.label}
          </button>
        )}
        <Link className="button small" to={finding.logs}>
          Open {finding.app}’s log <ChevronRight aria-hidden="true" size={14} />
        </Link>
        <span className="spacer" />
        <button
          className="small ghost"
          disabled={dismiss.isPending}
          onClick={() => dismiss.mutate({ dismiss: true, key: group.key, label: title })}
          type="button"
        >
          Dismiss
        </button>
      </footer>
    </article>
  );
}

function Dismissed({ items }: { items: Finding[] }): React.ReactNode {
  const dismiss = useDismiss();
  return (
    <details className={styles['dismissed']}>
      <summary>
        {items.length} dismissed issue{items.length === 1 ? '' : 's'}
      </summary>
      <ul className={styles['dismissedList']}>
        {items.map((finding) => {
          const title = finding.group.rule?.title ?? `${finding.app} keeps logging the same error`;
          return (
            <li key={finding.group.key}>
              <span className={styles['dismissedText']}>
                <strong>{title}</strong>
                <span className="small muted">
                  {finding.app} · logged {times(finding.group.count)} in the last day
                </span>
              </span>
              <button
                className="small ghost"
                disabled={dismiss.isPending}
                onClick={() => dismiss.mutate({ dismiss: false, key: finding.group.key, label: title })}
                type="button"
              >
                Show again
              </button>
            </li>
          );
        })}
      </ul>
    </details>
  );
}

const ORDER: Kind[] = ['problem', 'minor', 'unexplained', 'notice'];

/** Errors that keep coming back in the apps' logs, one card each; the known ones say what to do. */
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
  const open = all
    .filter((finding) => finding.group.dismissed !== true)
    .sort((a, b) => ORDER.indexOf(kindOf(a.group)) - ORDER.indexOf(kindOf(b.group)));
  const dismissed = all.filter((finding) => finding.group.dismissed === true);
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
      ) : (
        <>
          <p className="muted small">
            {open.length === 0
              ? `No error keeps coming back in the last day of ${problems.data.scanned} containers’ logs`
              : `${open.length} issue${open.length === 1 ? '' : 's'} in the last day of ${problems.data.scanned} containers’ logs`}
            , checked {formatRelative(problems.data.checked_at)}.
          </p>
          <div className={styles['issues']}>
            {open.map((finding) => (
              <Issue finding={finding} key={finding.group.key} />
            ))}
          </div>
          {dismissed.length === 0 ? null : <Dismissed items={dismissed} />}
        </>
      )}
    </section>
  );
}
