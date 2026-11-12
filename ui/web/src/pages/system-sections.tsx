import { Archive, ArrowDown, ArrowUp, Cpu, LoaderCircle, Network, Terminal } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import {
  useApps,
  useBackups,
  useJobs,
  useMeta,
  useResources,
  useRunBackup,
  useTailscale,
  useTailscaleServe,
} from '../api/queries';
import type { ContainerStats } from '../api/types';
import { useConfirm, useToast } from '../components/feedback';
import { Meter } from '../components/meter';
import { jobTitle } from '../components/shell';
import { StatusDot } from '../components/status-dot';
import { formatBytes, formatRelative, formatUptime } from '../format';
import styles from './system-page.module.css';

const TOP_CONTAINERS = 8;

export type ResourceSort = { descending: boolean; key: 'cpu' | 'memory' | 'name' };

const SORT_LABELS: Record<ResourceSort['key'], string> = { cpu: 'CPU', memory: 'Memory', name: 'Container' };

/** Containers in the order asked for; ties fall back to the name so rows do not jump about. */
export function sortContainers(containers: ContainerStats[], sort: ResourceSort): ContainerStats[] {
  const direction = sort.descending ? -1 : 1;
  const byName = (a: ContainerStats, b: ContainerStats): number => a.name.localeCompare(b.name);
  return [...containers].sort((a, b) => {
    if (sort.key === 'name') return direction * byName(a, b);
    const difference = sort.key === 'cpu' ? a.cpu_percent - b.cpu_percent : a.memory - b.memory;
    return direction * difference || byName(a, b);
  });
}

/** A column heading that sorts by its column; pressing it again reverses the order. */
function SortHeading({
  column,
  onSort,
  sort,
}: {
  column: ResourceSort['key'];
  onSort: (next: ResourceSort) => void;
  sort: ResourceSort;
}): React.ReactNode {
  const active = sort.key === column;
  // Names read best A to Z; for CPU and memory the biggest is what people look for.
  const next = { descending: active ? !sort.descending : column !== 'name', key: column };
  return (
    <th aria-sort={active ? (sort.descending ? 'descending' : 'ascending') : 'none'} scope="col">
      <button className={styles['sort']} onClick={() => onSort(next)} type="button">
        {SORT_LABELS[column]}
        {active ? (
          sort.descending ? (
            <ArrowDown aria-hidden="true" size={13} />
          ) : (
            <ArrowUp aria-hidden="true" size={13} />
          )
        ) : null}
      </button>
    </th>
  );
}

export function ResourcesCard(): React.ReactNode {
  const resources = useResources();
  const apps = useApps();
  const appFor = (container: string): string | undefined => {
    const app = apps.data?.find((a) => a.containers.some((c) => c.name === container));
    return app === undefined ? undefined : `/apps/${app.repo}/${app.role}`;
  };
  const [sort, setSort] = useState<ResourceSort>({ descending: true, key: 'cpu' });
  const [showAll, setShowAll] = useState(false);
  const host = resources.data?.host;
  const containers = sortContainers(resources.data?.containers ?? [], sort);
  const shown = showAll ? containers : containers.slice(0, TOP_CONTAINERS);
  const maxMemory = Math.max(1, ...containers.map((c) => c.memory));
  return (
    <section aria-labelledby="resources-title" className="card">
      <h2 className={styles['iconTitle']} id="resources-title">
        <Cpu aria-hidden="true" size={18} /> Resources
      </h2>
      {host === undefined ? (
        <p className="muted small">Reading…</p>
      ) : (
        <div className={styles['gauges']}>
          <div>
            <div className={styles['gaugeHead']}>
              <span>CPU load</span>
              <strong>{host.load_percent ?? '–'}%</strong>
            </div>
            <Meter label={`CPU load ${host.load_percent ?? 0}%`} percent={host.load_percent ?? 0} />
            <span className="muted small">
              {host.load.map((l) => l.toFixed(2)).join(' · ')} over 1, 5, 15 min · {host.cores} cores
            </span>
          </div>
          <div>
            <div className={styles['gaugeHead']}>
              <span>Memory</span>
              <strong>{host.memory_percent ?? '–'}%</strong>
            </div>
            <Meter label={`Memory ${host.memory_percent ?? 0}% used`} percent={host.memory_percent ?? 0} />
            <span className="muted small">
              {formatBytes(host.memory_used)} of {formatBytes(host.memory_total)}
            </span>
          </div>
          <div>
            <div className={styles['gaugeHead']}>
              <span>Up for</span>
            </div>
            <strong className={styles['uptime']}>{formatUptime(host.uptime)}</strong>
          </div>
        </div>
      )}
      {resources.data?.error ? <p className="note warn small">{resources.data.error}</p> : null}
      {shown.length === 0 ? null : (
        <table aria-label="Container resource use" className={styles['busiest']}>
          <thead>
            <tr>
              <SortHeading column="name" onSort={setSort} sort={sort} />
              <SortHeading column="cpu" onSort={setSort} sort={sort} />
              <SortHeading column="memory" onSort={setSort} sort={sort} />
            </tr>
          </thead>
          <tbody>
            {shown.map((c) => {
              const link = appFor(c.name);
              return (
                <tr key={c.name}>
                  <td>{link === undefined ? <code>{c.name}</code> : <Link to={link}>{c.name}</Link>}</td>
                  <td className={styles['num']}>{c.cpu_percent.toFixed(1)}%</td>
                  <td>
                    <div className={styles['memCell']}>
                      <span className={styles['num']}>{formatBytes(c.memory)}</span>
                      <span className={styles['memBar']}>
                        <span style={{ width: `${(c.memory / maxMemory) * 100}%` }} />
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {containers.length > TOP_CONTAINERS ? (
        <button className="small ghost" onClick={() => setShowAll(!showAll)} type="button">
          {showAll ? `Show the first ${TOP_CONTAINERS}` : `Show all ${containers.length} containers`}
        </button>
      ) : null}
    </section>
  );
}

function TailscaleAccess({
  owner,
  serve,
}: {
  owner: string;
  serve: { enabled: boolean; error?: string; url?: string };
}): React.ReactNode {
  const toggle = useTailscaleServe();
  const confirm = useConfirm();
  const toast = useToast();

  async function turnOn(): Promise<void> {
    const ok = await confirm({
      body: (
        <>
          <p>
            Makes this web app reachable at this server’s Tailscale address, over HTTPS, on port 8443. Only{' '}
            <strong>{owner}</strong> can open it: other people and tagged devices on your tailnet are refused.
          </p>
          <p>It works even when your domain, Cloudflare or Authelia are down.</p>
        </>
      ),
      confirmLabel: 'Turn on',
      title: 'Open the web app over Tailscale?',
    });
    if (!ok) return;
    toggle.mutate(true, {
      onError: (error) => toast({ body: error.message, title: 'Could not turn it on', tone: 'danger' }),
      onSuccess: () => toast({ title: 'Reachable over Tailscale', tone: 'ok' }),
    });
  }

  return (
    <div className={`${styles['access']} stack-sm`}>
      <strong>Web app over Tailscale</strong>
      {serve.enabled ? (
        <>
          <span className="small">
            On at{' '}
            <a href={serve.url} rel="noreferrer" target="_blank">
              {serve.url}
            </a>{' '}
            for {owner} only.
          </span>
          <div className="row">
            <button
              className="small"
              disabled={toggle.isPending}
              onClick={() =>
                toggle.mutate(false, {
                  onError: (error) => toast({ body: error.message, title: 'Could not turn it off', tone: 'danger' }),
                })
              }
              type="button"
            >
              Turn off
            </button>
          </div>
        </>
      ) : (
        <>
          <span className="muted small">
            Reach this app from your own devices on the tailnet, without your domain or Authelia. A way back in when
            something breaks.
          </span>
          <div className="row">
            <button className="small primary" disabled={toggle.isPending} onClick={() => void turnOn()} type="button">
              Turn on
            </button>
          </div>
        </>
      )}
      {serve.error ? <span className="muted small">{serve.error}</span> : null}
    </div>
  );
}

export function TailscaleCard(): React.ReactNode {
  const tailscale = useTailscale();
  const meta = useMeta();
  const data = tailscale.data;
  return (
    <section aria-labelledby="tailscale-title" className="card">
      <h2 className={styles['iconTitle']} id="tailscale-title">
        <Network aria-hidden="true" size={18} /> Tailscale
      </h2>
      {data === undefined ? (
        <p className="muted small">Reading…</p>
      ) : !data.installed ? (
        <p className="muted small">Tailscale is not installed on this server.</p>
      ) : !data.running ? (
        <>
          <StatusDot health={{ label: data.state || 'Not connected', tone: 'danger' }} />
          <p className="muted small">
            {data.error ?? 'Tailscale is not connected.'} Run <code>sudo tailscale up</code> on the server.
          </p>
        </>
      ) : (
        <div className="stack-sm">
          <StatusDot health={{ label: 'Connected', tone: 'ok' }} />
          <dl className={styles['facts']}>
            <dt>Name</dt>
            <dd>
              <code>{data.hostname}</code>
              {data.dns_name ? <span className="muted small"> · {data.dns_name}</span> : null}
            </dd>
            <dt>Addresses</dt>
            <dd>
              <code>{(data.addresses ?? []).join(', ')}</code>
            </dd>
            <dt>Account</dt>
            <dd>{data.owner}</dd>
            <dt>Devices</dt>
            <dd>
              {data.peers_online} of {data.peers} other devices online
            </dd>
          </dl>
          {data.serve === undefined ? null : <TailscaleAccess owner={data.owner ?? ''} serve={data.serve} />}
          <p className={`note small ${styles['tip']}`}>
            <Terminal aria-hidden="true" size={14} /> From any of your devices:{' '}
            <code>
              ssh {meta.data?.user ?? '<user>'}@{data.magic_dns === true ? data.hostname : (data.addresses?.[0] ?? '')}
            </code>
          </p>
        </div>
      )}
    </section>
  );
}

export function BackupsCard(): React.ReactNode {
  const backups = useBackups();
  const jobs = useJobs();
  const run = useRunBackup();
  const confirm = useConfirm();
  const toast = useToast();
  const data = backups.data;
  const busy = jobs.data?.busy ?? false;

  async function backUp(): Promise<void> {
    const ok = await confirm({
      body: (
        <>
          <p>
            Runs <code>sb install backup</code>. Saltbox stops your apps while it archives <code>/opt</code>, then
            starts them again; expect them to be down for a while on a big library.
          </p>
          <p>The backup goes to every destination enabled in backup_config.yml.</p>
        </>
      ),
      confirmLabel: 'Back up now',
      title: 'Back up Saltbox now?',
    });
    if (!ok) return;
    run.mutate(undefined, {
      onError: (error) => toast({ body: error.message, title: 'Could not start the backup', tone: 'danger' }),
      onSuccess: (job) =>
        toast({ href: `/activity/${job.id}`, linkLabel: 'Watch the log', title: 'Backup started', tone: 'info' }),
    });
  }

  return (
    <section aria-labelledby="backups-title" className="card">
      <div className="row">
        <h2 className={`${styles['iconTitle']} ${styles['flush']}`} id="backups-title">
          <Archive aria-hidden="true" size={18} /> Backups
        </h2>
        <span className="spacer" />
        <button className="small" disabled={busy || run.isPending} onClick={() => void backUp()} type="button">
          {run.isPending ? <LoaderCircle aria-hidden="true" className="spin" size={14} /> : null} Back up now
        </button>
      </div>
      {data === undefined ? (
        <p className="muted small">Reading…</p>
      ) : !data.configured ? (
        <p className="muted small">
          No backup_config.yml yet. Set one up on the <Link to="/config/backup_config">Config</Link> page.
        </p>
      ) : (
        <div className="stack-sm">
          <dl className={styles['facts']}>
            <dt>Last backup</dt>
            <dd>
              {data.latest === null ? (
                <span className="muted">none found in the local destination</span>
              ) : (
                <>
                  {formatRelative(data.latest.modified)} · {formatBytes(data.latest.size)}
                </>
              )}
            </dd>
            <dt>Last run here</dt>
            <dd>
              {data.last_job === null ? (
                <span className="muted">never</span>
              ) : (
                <Link to={`/activity/${data.last_job.id}`}>
                  {jobTitle(data.last_job)} {data.last_job.status} {formatRelative(data.last_job.started_at)}
                </Link>
              )}
            </dd>
            <dt>Schedule</dt>
            <dd>{data.schedule === '' ? 'not scheduled' : data.schedule}</dd>
          </dl>
          <ul className={styles['destinations']}>
            {data.destinations.map((d) => (
              <li key={d.kind}>
                <StatusDot health={{ label: d.enabled ? 'On' : 'Off', tone: d.enabled ? 'ok' : 'muted' }} />
                <span className={styles['destKind']}>{d.kind}</span>
                <code className={styles['destPath']}>{d.destination}</code>
              </li>
            ))}
          </ul>
          <Link className="small" to="/config/backup_config">
            Change destinations and schedule
          </Link>
        </div>
      )}
    </section>
  );
}
