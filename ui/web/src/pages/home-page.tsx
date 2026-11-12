import {
  ArrowUpCircle,
  CircleAlert,
  CircleCheck,
  ExternalLink,
  Info,
  LoaderCircle,
  PackagePlus,
  Star,
  TriangleAlert,
} from 'lucide-react';
import { Link } from 'react-router-dom';

import { useApps, useJobs, useMedia, useOverview, useStartJob, useUpdates } from '../api/queries';
import type { App, Job } from '../api/types';
import { AppAvatar } from '../components/app-avatar';
import { useToast } from '../components/feedback';
import { Meter } from '../components/meter';
import { ErrorMessage, Loading } from '../components/query-state';
import { jobTitle } from '../components/shell';
import { StatusDot } from '../components/status-dot';
import { formatBytes, formatRelative } from '../format';
import { useContainerActions, useJobActions } from '../lib/actions';
import { usePins } from '../lib/pins';
import { appHealth, hostOf } from '../lib/status';
import { type Attention, type AttentionAction, attentionItems } from './home-attention';
import { MediaRow, mediaAttention } from './home-media';
import styles from './home-page.module.css';

export { attentionItems } from './home-attention';

const TONE_ICONS = {
  danger: <CircleAlert aria-hidden="true" size={20} />,
  info: <Info aria-hidden="true" size={20} />,
  warn: <TriangleAlert aria-hidden="true" size={20} />,
};

function ActionButton({ action }: { action: AttentionAction }): React.ReactNode {
  const containers = useContainerActions();
  const jobs = useJobActions();
  const start = useStartJob();
  const recent = useJobs();
  const toast = useToast();
  switch (action.kind) {
    case 'link':
    case 'logs':
      return (
        <Link className="button small" to={action.to}>
          {action.label}
        </Link>
      );
    case 'restart':
    case 'start':
      return (
        <button
          className="small primary"
          disabled={containers.pending}
          onClick={() => void containers.run(action.container, action.kind)}
          type="button"
        >
          {action.label}
        </button>
      );
    case 'update':
      return (
        <button className="small primary" onClick={() => void jobs.updateApp(action.app)} type="button">
          {action.label}
        </button>
      );
    case 'updateAll':
      return (
        <button className="small primary" onClick={() => void jobs.updateAll(action.apps)} type="button">
          {action.label}
        </button>
      );
    case 'sbUpdate':
      return (
        <button className="small primary" onClick={() => void jobs.updateSaltbox()} type="button">
          {action.label}
        </button>
      );
    case 'retry': {
      const job = recent.data?.jobs.find((j) => j.id === action.jobId);
      if (job === undefined || job.kind === 'validate') return null;
      return (
        <button
          className="small"
          disabled={start.isPending || recent.data?.busy === true}
          onClick={() =>
            start.mutate(
              { kind: job.kind === 'update' ? 'update' : 'install', tags: job.tags },
              {
                onError: (error) => toast({ body: error.message, title: 'Could not start the job', tone: 'danger' }),
                onSuccess: (started) =>
                  toast({ href: `/activity/${started.id}`, title: `Running ${jobTitle(started)}`, tone: 'info' }),
              },
            )
          }
          type="button"
        >
          {action.label}
        </button>
      );
    }
  }
}

function AttentionList({ items }: { items: Attention[] }): React.ReactNode {
  return (
    <ul className={styles['attention']}>
      {items.map((item) => (
        <li className={`${styles['item']} ${styles[item.tone]}`} key={item.id}>
          <span className={styles['itemIcon']}>{TONE_ICONS[item.tone]}</span>
          <div className={styles['itemText']}>
            <strong>{item.title}</strong>
            {item.detail === undefined ? null : <span className="muted small">{item.detail}</span>}
          </div>
          {item.actions.length === 0 ? null : (
            <div className={styles['itemActions']}>
              {item.actions.map((action) => (
                <ActionButton action={action} key={`${action.kind}:${action.label}`} />
              ))}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function Launcher({ apps }: { apps: App[] }): React.ReactNode {
  const { isPinned, toggle } = usePins();
  const id = (app: App): string => `${app.repo}/${app.role}`;
  const sorted = [...apps].sort(
    (a, b) => Number(isPinned(id(b))) - Number(isPinned(id(a))) || a.title.localeCompare(b.title),
  );
  return (
    <section aria-labelledby="launcher-title">
      <div className={styles['sectionHead']}>
        <h2 id="launcher-title">Your apps</h2>
        <span className="muted small">Star the ones you use most to keep them first.</span>
        <span className="spacer" />
        <Link className="button small ghost" to="/apps/discover">
          <PackagePlus aria-hidden="true" size={16} /> Add apps
        </Link>
      </div>
      {apps.length === 0 ? (
        <div className="card empty">
          <p>No apps installed yet.</p>
          <Link className="button primary" to="/apps/discover">
            Browse the catalog
          </Link>
        </div>
      ) : (
        <ul className={styles['launcher']}>
          {sorted.map((app) => {
            const url = app.urls[0];
            const health = appHealth(app);
            const pinned = isPinned(id(app));
            const body = (
              <>
                <AppAvatar title={app.title} url={url} />
                <span className={styles['tileText']}>
                  <span className={styles['tileTitle']}>{app.title}</span>
                  <StatusDot health={health} />
                </span>
                {url === undefined ? null : (
                  <ExternalLink aria-hidden="true" className={styles['tileOpen']} size={14} />
                )}
              </>
            );
            return (
              <li className={styles['tileWrap']} key={id(app)}>
                {url === undefined ? (
                  <Link className={styles['tile']} to={`/apps/${app.repo}/${app.role}`}>
                    {body}
                  </Link>
                ) : (
                  <a
                    aria-label={`Open ${app.title} (${hostOf(url)})`}
                    className={styles['tile']}
                    href={url}
                    rel="noreferrer"
                    target="_blank"
                    title={hostOf(url)}
                  >
                    {body}
                  </a>
                )}
                <button
                  aria-label={pinned ? `Unpin ${app.title}` : `Pin ${app.title}`}
                  aria-pressed={pinned}
                  className={`ghost icon small ${styles['pin']} ${pinned ? styles['pinned'] : ''}`}
                  onClick={() => toggle(id(app))}
                  type="button"
                >
                  <Star aria-hidden="true" fill={pinned ? 'currentColor' : 'none'} size={15} />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function UpdatesCard({ apps }: { apps: App[] }): React.ReactNode {
  const updates = useUpdates();
  const actions = useJobActions();
  const pending = apps.filter((app) => app.update_available);
  const repos = updates.data?.repos ?? [];
  const behind = repos.filter((repo) => repo.status === 'update');
  return (
    <section aria-labelledby="updates-title" className="card">
      <h3 id="updates-title">Updates</h3>
      {updates.data?.running === true ? (
        <p className="muted small">
          <LoaderCircle className="spin" size={14} /> Checking…
        </p>
      ) : (
        <p className="muted small">
          {updates.data?.checked_at == null ? 'Not checked yet' : `Checked ${formatRelative(updates.data.checked_at)}`}
        </p>
      )}
      <ul className={styles['plain']}>
        <li>
          {pending.length === 0 ? (
            <span className={styles['ok']}>
              <CircleCheck aria-hidden="true" size={16} /> Apps are up to date
            </span>
          ) : (
            <span className={styles['due']}>
              <ArrowUpCircle aria-hidden="true" size={16} /> {pending.length} app{pending.length === 1 ? '' : 's'}:{' '}
              {pending.map((a) => a.title).join(', ')}
            </span>
          )}
        </li>
        <li>
          {behind.length === 0 ? (
            <span className={styles['ok']}>
              <CircleCheck aria-hidden="true" size={16} /> Saltbox is up to date
            </span>
          ) : (
            <span className={styles['due']}>
              <ArrowUpCircle aria-hidden="true" size={16} /> Saltbox has new commits
            </span>
          )}
        </li>
      </ul>
      <div className="row">
        {pending.length > 0 ? (
          <button className="small primary" onClick={() => void actions.updateAll(pending)} type="button">
            Update apps
          </button>
        ) : null}
        {behind.length > 0 ? (
          <button className="small" onClick={() => void actions.updateSaltbox()} type="button">
            Run sb update
          </button>
        ) : null}
      </div>
    </section>
  );
}

function StorageCard(): React.ReactNode {
  const overview = useOverview();
  const disks = overview.data?.host.disks ?? [];
  return (
    <section aria-labelledby="storage-title" className="card">
      <div className={styles['sectionHead']}>
        <h3 id="storage-title">Storage</h3>
        <span className="spacer" />
        <Link className="small" to="/system">
          Details
        </Link>
      </div>
      <ul className={styles['plain']}>
        {disks.map((disk) => (
          <li key={disk.path}>
            <div className={styles['diskLine']}>
              <code>{(disk.paths ?? [disk.path]).join(' · ')}</code>
              <span className="muted small">{formatBytes(disk.free)} free</span>
            </div>
            <Meter percent={disk.percent} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function ActivityCard({ jobs }: { jobs: Job[] }): React.ReactNode {
  return (
    <section aria-labelledby="activity-title" className="card">
      <div className={styles['sectionHead']}>
        <h3 id="activity-title">Recent activity</h3>
        <span className="spacer" />
        <Link className="small" to="/activity">
          All
        </Link>
      </div>
      {jobs.length === 0 ? (
        <p className="muted small">Nothing has run from here yet.</p>
      ) : (
        <ul className={styles['plain']}>
          {jobs.slice(0, 5).map((job) => (
            <li className={styles['jobLine']} key={job.id}>
              <StatusDot
                health={{
                  label: job.status,
                  tone:
                    job.status === 'succeeded'
                      ? 'ok'
                      : job.status === 'failed'
                        ? 'danger'
                        : job.status === 'running'
                          ? 'warn'
                          : 'muted',
                }}
                showLabel={false}
              />
              <Link className={styles['jobName']} to={`/activity/${job.id}`}>
                {jobTitle(job)}
              </Link>
              <span className="muted small">{formatRelative(job.started_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function HomePage(): React.ReactNode {
  const overview = useOverview();
  const apps = useApps();
  const media = useMedia();
  if (overview.isPending) return <Loading what="your server" />;
  if (overview.isError) return <ErrorMessage error={overview.error} prefix="Home" />;
  const data = overview.data;
  const all = apps.data ?? [];
  const installed = all.filter((app) => app.installed);
  const attention = [...mediaAttention(media.data), ...attentionItems(data, all)];
  const urgent = attention.filter((item) => item.tone !== 'info').length;
  const running = data.containers.running;
  return (
    <div className="stack">
      <header className={styles['hero']}>
        <div className={`${styles['heroIcon']} ${urgent > 0 ? styles['heroBad'] : styles['heroGood']}`}>
          {urgent > 0 ? <CircleAlert size={28} /> : <CircleCheck size={28} />}
        </div>
        <div>
          <h1 className={styles['heroTitle']}>
            {urgent > 0
              ? `${urgent} thing${urgent === 1 ? '' : 's'} need${urgent === 1 ? 's' : ''} your attention`
              : 'Everything is running'}
          </h1>
          <p className="muted">
            {data.containers.available
              ? `${running} of ${data.containers.total} containers running` +
                (apps.data === undefined ? '' : ` · ${installed.length} apps installed`)
              : 'Container status unavailable'}
          </p>
        </div>
      </header>

      {attention.length === 0 ? null : (
        <section aria-label="Needs attention" className="card">
          <AttentionList items={attention} />
        </section>
      )}

      <MediaRow media={media.data} />

      <div className={styles['columns']}>
        <Launcher apps={installed} />
        <aside className={styles['rail']}>
          <UpdatesCard apps={installed} />
          <StorageCard />
          <ActivityCard jobs={data.jobs.recent} />
        </aside>
      </div>
    </div>
  );
}
