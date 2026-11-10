import { CircleAlert, CircleCheck, CircleDashed, CircleMinus, Hand, LoaderCircle } from 'lucide-react';

import { useApplySetup, useSetup } from '../api/queries';
import type { SetupStatus, SetupTask } from '../api/types';
import { useConfirm, useToast } from '../components/feedback';
import { ErrorMessage, Loading } from '../components/query-state';
import styles from './connect-page.module.css';

const ICONS: Record<SetupStatus, React.ReactNode> = {
  done: <CircleCheck aria-hidden="true" size={18} />,
  error: <CircleAlert aria-hidden="true" size={18} />,
  manual: <Hand aria-hidden="true" size={18} />,
  skip: <CircleMinus aria-hidden="true" size={18} />,
  todo: <CircleDashed aria-hidden="true" size={18} />,
};

const LABELS: Record<SetupStatus, string> = {
  done: 'Done',
  error: 'Problem',
  manual: 'Do this yourself',
  skip: 'Skipped',
  todo: 'To do',
};

export function groupByApp(tasks: SetupTask[]): [string, SetupTask[]][] {
  const groups = new Map<string, SetupTask[]>();
  for (const task of tasks) groups.set(task.app, [...(groups.get(task.app) ?? []), task]);
  return [...groups.entries()];
}

export function ConnectPage(): React.ReactNode {
  const setup = useSetup();
  const apply = useApplySetup();
  const confirm = useConfirm();
  const toast = useToast();
  if (setup.isPending) return <Loading what="app connections" />;
  if (setup.isError) return <ErrorMessage error={setup.error} prefix="Connect apps" />;
  const { summary, tasks } = setup.data;
  const todo = (summary.todo ?? 0) + (summary.error ?? 0);

  async function run(): Promise<void> {
    const ok = await confirm({
      body: (
        <>
          <p>
            Adds the connections the Saltbox docs walk you through: download clients, root folders, indexers, Plex
            libraries and the recommended settings. Anything already set up is left as it is.
          </p>
          <p>Takes up to a minute. Apps keep running.</p>
        </>
      ),
      confirmLabel: 'Connect the apps',
      title: `Set up ${todo} connection${todo === 1 ? '' : 's'}?`,
    });
    if (!ok) return;
    apply.mutate(undefined, {
      onError: (error) => toast({ body: error.message, title: 'Setup stopped', tone: 'danger' }),
      onSuccess: (data) =>
        toast({
          body: `${data.summary.done ?? 0} done, ${data.summary.error ?? 0} with problems`,
          title: 'Apps connected',
          tone: (data.summary.error ?? 0) > 0 ? 'danger' : 'ok',
        }),
    });
  }

  return (
    <div className="stack">
      <div className="row">
        <h1 className={styles['flush']}>Connect apps</h1>
        <span className="spacer" />
        <button disabled={apply.isPending || setup.isFetching} onClick={() => void setup.refetch()} type="button">
          Check again
        </button>
        <button className="primary" disabled={apply.isPending || todo === 0} onClick={() => void run()} type="button">
          {apply.isPending ? <LoaderCircle aria-hidden="true" className="spin" size={16} /> : null}
          {apply.isPending ? 'Connecting…' : todo === 0 ? 'All connected' : `Connect ${todo}`}
        </button>
      </div>
      <p className="muted">
        Wires your installed apps together the way the Saltbox docs describe, so Sonarr and Radarr can reach your
        download clients and indexers, and Plex sees your library. Safe to run again at any time.
      </p>
      <div className="chips">
        {(['done', 'todo', 'error', 'manual', 'skip'] as const).map((status) => (
          <span className={`${styles['pill']} ${styles[status]}`} key={status}>
            {ICONS[status]} {summary[status] ?? 0} {LABELS[status].toLowerCase()}
          </span>
        ))}
      </div>
      {tasks.length === 0 ? (
        <div className="card empty">
          <p>No supported apps are installed yet.</p>
        </div>
      ) : (
        <div className={styles['apps']}>
          {groupByApp(tasks).map(([app, list]) => (
            <section aria-label={app} className="card" key={app}>
              <h2>{app}</h2>
              <ul className={styles['tasks']}>
                {list.map((task) => (
                  <li className={styles[task.status]} key={task.id}>
                    <span className={styles['icon']} title={LABELS[task.status]}>
                      {ICONS[task.status]}
                    </span>
                    <span className={styles['task']}>
                      <span className={styles['taskTitle']}>{task.title}</span>
                      {task.detail === '' ? null : <span className={styles['detail']}>{task.detail}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
