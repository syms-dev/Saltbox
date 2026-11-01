import { Link } from 'react-router-dom';

import { useOverview } from '../api/queries';
import type { Issue, Overview } from '../api/types';
import { ErrorMessage, Loading } from '../components/query-state';
import { StatusBadge } from '../components/status-badge';
import { formatBytes, formatWhen } from '../format';
import styles from './overview-page.module.css';

const DISK_WARN_PERCENT = 85;

type Attention = { href?: string; text: string; tone: 'danger' | 'warn' };

function attentionItems(data: Overview): Attention[] {
  const items: Attention[] = [];
  for (const [file, issues] of Object.entries(data.config_issues)) {
    const errors = issues.filter((i: Issue) => i.level === 'error');
    if (errors.length > 0) {
      items.push({
        href: file === 'inventory' ? '/config/inventory' : `/config/${file}`,
        text: `${file}: ${errors.length} validation error${errors.length === 1 ? '' : 's'}`,
        tone: 'danger',
      });
    }
  }
  for (const name of data.containers.unhealthy) items.push({ text: `${name} is unhealthy`, tone: 'danger' });
  for (const name of data.containers.stopped) items.push({ text: `${name} is not running`, tone: 'warn' });
  for (const disk of data.host.disks) {
    if (disk.percent >= DISK_WARN_PERCENT) {
      items.push({ text: `${disk.path} is ${disk.percent}% full (${formatBytes(disk.free)} free)`, tone: 'warn' });
    }
  }
  if (data.host.reboot_required) items.push({ text: 'A reboot is pending', tone: 'warn' });
  const last = data.jobs.recent[0];
  if (last !== undefined && last.status === 'failed') {
    items.push({
      href: `/jobs/${last.id}`,
      text: `The last job (${last.kind} ${last.tags.join(',')}) failed`,
      tone: 'danger',
    });
  }
  if (!data.install.installed) items.push({ text: 'Saltbox is not installed on this server yet', tone: 'warn' });
  return items;
}

export function OverviewPage(): React.ReactNode {
  const overview = useOverview();
  if (overview.isPending) return <Loading what="overview" />;
  if (overview.isError) return <ErrorMessage error={overview.error} prefix="Overview" />;
  const data = overview.data;
  const attention = attentionItems(data);
  return (
    <div className="stack">
      <h1>Overview</h1>
      <section aria-labelledby="attention" className="card">
        <h2 id="attention">Needs attention</h2>
        {attention.length === 0 ? (
          <p className="muted">Nothing. Everything the daemon can see looks fine.</p>
        ) : (
          <ul className={styles['attention']}>
            {attention.map((item) => (
              <li className={styles[item.tone]} key={item.text}>
                {item.href === undefined ? item.text : <Link to={item.href}>{item.text}</Link>}
              </li>
            ))}
          </ul>
        )}
      </section>
      <div className="grid">
        <section className="card">
          <h3>Containers</h3>
          {data.containers.available ? (
            <p>
              <strong>{data.containers.running}</strong> of {data.containers.total} managed containers running
            </p>
          ) : (
            <p className="muted">Docker is not reachable from the daemon.</p>
          )}
        </section>
        <section className="card">
          <h3>Jobs</h3>
          {data.jobs.current === null ? (
            <p className="muted">Idle</p>
          ) : (
            <p>
              <StatusBadge status={data.jobs.current.status} />{' '}
              <Link to={`/jobs/${data.jobs.current.id}`}>
                {data.jobs.current.kind} {data.jobs.current.tags.join(',')}
              </Link>
            </p>
          )}
          <ul className={styles['plain']}>
            {data.jobs.recent.map((job) => (
              <li key={job.id}>
                <StatusBadge status={job.status} />{' '}
                <Link to={`/jobs/${job.id}`}>
                  {job.kind} {job.tags.join(',')}
                </Link>{' '}
                <span className="muted">{formatWhen(job.started_at)}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h3>Disks</h3>
          <ul className={styles['plain']}>
            {data.host.disks.map((disk) => (
              <li key={disk.path}>
                <code>{disk.path}</code> {disk.percent}% used, {formatBytes(disk.free)} free of{' '}
                {formatBytes(disk.total)}
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h3>Mounts</h3>
          {data.host.mounts.length === 0 ? (
            <p className="muted">No rclone or mergerfs mounts.</p>
          ) : (
            <ul className={styles['plain']}>
              {data.host.mounts.map((mount) => (
                <li key={mount.target}>
                  <code>{mount.target}</code> <span className="muted">{mount.type}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <section className="card">
        <h2>Services</h2>
        {data.services.length === 0 ? (
          <p className="muted">
            No MOTD config yet. Run <code>sb install motd-generate-config</code> after the install to list URLs and
            logins here.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Service</th>
                <th>Name</th>
                <th>URL</th>
              </tr>
            </thead>
            <tbody>
              {data.services.map((service, index) => (
                <tr key={`${service.service}-${index}`}>
                  <td>{service.service}</td>
                  <td>{typeof service['name'] === 'string' ? service['name'] : ''}</td>
                  <td>{typeof service['url'] === 'string' ? <a href={service['url']}>{service['url']}</a> : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
