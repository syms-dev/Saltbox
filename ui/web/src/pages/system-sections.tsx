import { Archive, Cpu, LoaderCircle, Network, Terminal } from 'lucide-react';
import { Link } from 'react-router-dom';

import { useApps, useBackups, useJobs, useMeta, useResources, useRunBackup, useTailscale } from '../api/queries';
import { useConfirm, useToast } from '../components/feedback';
import { Meter } from '../components/meter';
import { jobTitle } from '../components/shell';
import { StatusDot } from '../components/status-dot';
import { formatBytes, formatRelative, formatUptime } from '../format';
import styles from './system-page.module.css';

const TOP_CONTAINERS = 8;

export function ResourcesCard(): React.ReactNode {
  const resources = useResources();
  const apps = useApps();
  const appFor = (container: string): string | undefined => {
    const app = apps.data?.find((a) => a.containers.some((c) => c.name === container));
    return app === undefined ? undefined : `/apps/${app.repo}/${app.role}`;
  };
  const host = resources.data?.host;
  const busiest = (resources.data?.containers ?? []).slice(0, TOP_CONTAINERS);
  const maxMemory = Math.max(1, ...busiest.map((c) => c.memory));
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
      {busiest.length === 0 ? null : (
        <table aria-label="Busiest containers" className={styles['busiest']}>
          <thead>
            <tr>
              <th>Container</th>
              <th>CPU</th>
              <th>Memory</th>
            </tr>
          </thead>
          <tbody>
            {busiest.map((c) => {
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
    </section>
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
